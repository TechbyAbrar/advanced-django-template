"""
chat/sio_server.py
==================
Production-grade Socket.IO server for the chat application.

Architecture:
  - python-socketio with ASGI adapter (works with uvicorn / gunicorn + uvicorn workers)
  - Redis as the message queue / pub-sub transport (AsyncRedisManager)
  - JWT-based socket authentication (no cookie dependency)
  - Rooms follow the pattern:  conv_<conversation_uuid>
  - User-level room: user_<user_id>  (for personal notifications)

Events emitted by SERVER → CLIENT:
  message:new          — new message fanned out to room
  message:updated      — edit / delete notification
  receipt:update       — delivered / read receipt
  reaction:update      — emoji reaction change
  presence:change      — user online / offline / typing
  unread:update        — per-conversation unread counter refresh
  conversation:new     — new conversation created (arrives in user room)
  error                — structured error payload

Events emitted by CLIENT → SERVER:
  authenticate         — send JWT token after connect
  message:send         — send a new message (with idempotency key)
  message:edit         — edit own message
  message:delete       — soft-delete own message
  message:read         — mark conversation as read up to a message_id
  typing:start         — broadcast typing indicator
  typing:stop          — stop typing indicator
  reaction:add         — add emoji reaction
  reaction:remove      — remove emoji reaction
  conversation:join    — join/subscribe to a conversation room
  conversation:leave   — leave room without leaving conversation
"""

import logging
import asyncio
from datetime import timezone as dt_tz, datetime

import socketio
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("chat.sio")

# ---------------------------------------------------------------------------
# Socket.IO manager — swap AsyncRedisManager for production Redis
# ---------------------------------------------------------------------------
REDIS_URL = getattr(settings, "SOCKETIO_REDIS_URL", "redis://localhost:6379/1")

mgr = socketio.AsyncRedisManager(REDIS_URL)

sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=mgr,
    cors_allowed_origins=getattr(settings, "SOCKETIO_CORS_ORIGINS", "*"),
    logger=False,
    engineio_logger=False,
    ping_interval=25,
    ping_timeout=60,
    max_http_buffer_size=10 * 1024 * 1024,  # 10 MB max payload
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_from_token(token: str):
    """Validate JWT and return UserAuth instance or None."""
    try:
        from rest_framework_simplejwt.tokens import UntypedToken
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
        from django.contrib.auth import get_user_model

        User = get_user_model()
        UntypedToken(token)  # validates signature + expiry
        from rest_framework_simplejwt.tokens import AccessToken
        decoded = AccessToken(token)
        user_id = decoded.get("user_id")
        user = await sync_to_async(User.objects.get)(pk=user_id)
        return user
    except Exception as exc:
        logger.warning("Token validation failed: %s", exc)
        return None


async def _assert_participant(user, conversation_id: str):
    """Raise PermissionError if user is not an active participant."""
    from chat.models import Participant
    exists = await sync_to_async(
        Participant.objects.filter(
            conversation_id=conversation_id, user=user, left_at__isnull=True
        ).exists
    )()
    if not exists:
        raise PermissionError("Not a participant")


def _room(conversation_id: str) -> str:
    return f"conv_{conversation_id}"


def _user_room(user_id) -> str:
    return f"user_{user_id}"


async def _log_presence(user, event: str, sid: str, environ: dict = None):
    from chat.models import PresenceLog
    ip = None
    ua = ""
    if environ:
        ip = (environ.get("HTTP_X_FORWARDED_FOR") or environ.get("REMOTE_ADDR", "")).split(",")[0].strip()
        ua = environ.get("HTTP_USER_AGENT", "")
    await sync_to_async(PresenceLog.objects.create)(
        user=user, event=event, socket_id=sid, ip_address=ip or None, user_agent=ua
    )


# ---------------------------------------------------------------------------
# Session store  (sid → authenticated user)
# ---------------------------------------------------------------------------
_sessions: dict[str, object] = {}   # sid → UserAuth


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

@sio.event
async def connect(sid, environ, auth):
    """
    Client must pass   { token: "<jwt>" }  in the auth dict.
    We allow the socket to connect but mark it unauthenticated until
    authenticate event fires — OR we reject immediately if auth dict provided.
    """
    token = (auth or {}).get("token") if auth else None
    if token:
        user = await _get_user_from_token(token)
        if not user:
            logger.info("SIO connect rejected — bad token sid=%s", sid)
            return False   # reject connection
        _sessions[sid] = user
        await sio.enter_room(sid, _user_room(user.pk))
        await _mark_online(user, sid, environ)
        logger.info("SIO connected: user=%s sid=%s", user.pk, sid)
    # If no auth dict, we keep the socket in unauthenticated state;
    # client must send `authenticate` event within 10 s or we disconnect.
    else:
        asyncio.ensure_future(_timeout_unauth(sid))


@sio.event
async def disconnect(sid):
    user = _sessions.pop(sid, None)
    if user:
        await _mark_offline(user, sid)
        logger.info("SIO disconnected: user=%s sid=%s", user.pk, sid)


async def _timeout_unauth(sid):
    await asyncio.sleep(10)
    if sid not in _sessions:
        logger.info("Disconnecting unauthenticated socket sid=%s", sid)
        await sio.disconnect(sid)


async def _mark_online(user, sid, environ=None):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    await sync_to_async(User.objects.filter(pk=user.pk).update)(is_online=True)
    await _log_presence(user, "connect", sid, environ)
    # Broadcast to all conversations this user belongs to
    await _broadcast_presence(user, "online")


async def _mark_offline(user, sid):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    # Only mark offline if no other active sessions
    active_sessions = [u for s, u in _sessions.items() if u and u.pk == user.pk]
    if not active_sessions:
        await sync_to_async(User.objects.filter(pk=user.pk).update)(
            is_online=False, last_activity=timezone.now()
        )
        await _broadcast_presence(user, "offline")
    await _log_presence(user, "disconnect", sid)


async def _broadcast_presence(user, status: str):
    """Notify all conversation rooms the user is part of."""
    from chat.models import Participant
    conv_ids = await sync_to_async(list)(
        Participant.objects.filter(user=user, left_at__isnull=True).values_list("conversation_id", flat=True)
    )
    payload = {
        "user_id": str(user.pk),
        "status": status,
        "last_activity": timezone.now().isoformat(),
    }
    for conv_id in conv_ids:
        await sio.emit("presence:change", payload, room=_room(str(conv_id)))


# ---------------------------------------------------------------------------
# authenticate  (fallback when token passed in event instead of handshake)
# ---------------------------------------------------------------------------

@sio.event
async def authenticate(sid, data):
    token = (data or {}).get("token", "")
    user = await _get_user_from_token(token)
    if not user:
        await sio.emit("error", {"code": "AUTH_FAILED", "message": "Invalid token"}, to=sid)
        await sio.disconnect(sid)
        return
    _sessions[sid] = user
    await sio.enter_room(sid, _user_room(user.pk))
    await _mark_online(user, sid)
    await sio.emit("authenticated", {"user_id": str(user.pk)}, to=sid)


# ---------------------------------------------------------------------------
# conversation:join / leave
# ---------------------------------------------------------------------------

@sio.event
async def conversation_join(sid, data):
    user = _sessions.get(sid)
    if not user:
        return await _emit_error(sid, "UNAUTHENTICATED")
    conv_id = data.get("conversation_id")
    try:
        await _assert_participant(user, conv_id)
    except PermissionError:
        return await _emit_error(sid, "FORBIDDEN", "Not a participant")

    await sio.enter_room(sid, _room(conv_id))
    # Deliver any missed messages since last_read
    await _deliver_missed_messages(sid, user, conv_id)


@sio.event
async def conversation_leave(sid, data):
    conv_id = data.get("conversation_id")
    await sio.leave_room(sid, _room(conv_id))


async def _deliver_missed_messages(sid, user, conv_id: str):
    """Fan-out messages created after user's last_read_at — recovery on reconnect."""
    from chat.models import Participant, Message
    from chat.serializers import MessageSerializer

    participant = await sync_to_async(
        Participant.objects.filter(conversation_id=conv_id, user=user).first
    )()
    if not participant:
        return

    qs = Message.objects.filter(
        conversation_id=conv_id, is_deleted=False
    ).exclude(sender=user).select_related("sender").prefetch_related("attachments", "receipts")

    if participant.last_read_at:
        qs = qs.filter(created_at__gt=participant.last_read_at)

    messages = await sync_to_async(list)(qs.order_by("created_at")[:200])
    if messages:
        data = await sync_to_async(MessageSerializer(messages, many=True).data.__class__)(
            MessageSerializer(messages, many=True).data
        )
        await sio.emit("message:missed", {"messages": list(data)}, to=sid)


# ---------------------------------------------------------------------------
# message:send
# ---------------------------------------------------------------------------

@sio.event
async def message_send(sid, data):
    user = _sessions.get(sid)
    if not user:
        return await _emit_error(sid, "UNAUTHENTICATED")

    conv_id           = data.get("conversation_id")
    body              = data.get("body", "").strip()
    client_message_id = data.get("client_message_id")   # idempotency key
    reply_to_id       = data.get("reply_to_id")
    message_type      = data.get("message_type", "text")

    if not conv_id:
        return await _emit_error(sid, "VALIDATION", "conversation_id required")

    try:
        await _assert_participant(user, conv_id)
    except PermissionError:
        return await _emit_error(sid, "FORBIDDEN")

    # --- Idempotency check ---
    if client_message_id:
        from chat.models import Message
        existing = await sync_to_async(
            Message.objects.filter(client_message_id=client_message_id).first
        )()
        if existing:
            from chat.serializers import MessageSerializer
            payload = await sync_to_async(lambda: MessageSerializer(existing).data)()
            await sio.emit("message:ack", {"message": dict(payload), "duplicate": True}, to=sid)
            return

    # --- Persist ---
    from chat.models import Message, Conversation, Participant
    message = await sync_to_async(Message.objects.create)(
        conversation_id=conv_id,
        sender=user,
        body=body,
        message_type=message_type,
        client_message_id=client_message_id,
        reply_to_id=reply_to_id,
    )

    # Bump conversation updated_at for inbox ordering
    await sync_to_async(Conversation.objects.filter(pk=conv_id).update)(updated_at=timezone.now())

    # --- Create delivery receipts for all other participants ---
    await _create_receipts(message, user, conv_id)

    # --- Serialize ---
    from chat.serializers import MessageSerializer
    payload = await sync_to_async(lambda: MessageSerializer(message).data)()

    # --- ACK to sender ---
    await sio.emit("message:ack", {"message": dict(payload)}, to=sid)

    # --- Fan-out to room ---
    await sio.emit("message:new", {"message": dict(payload)}, room=_room(conv_id), skip_sid=sid)

    # --- Unread counter push to each participant ---
    await _push_unread_counters(conv_id, sender=user)


async def _create_receipts(message, sender, conv_id: str):
    from chat.models import Participant, MessageReceipt
    participants = await sync_to_async(list)(
        Participant.objects.filter(conversation_id=conv_id, left_at__isnull=True)
        .exclude(user=sender).values_list("user_id", flat=True)
    )
    receipts = [
        MessageReceipt(message=message, recipient_id=uid, status="sent")
        for uid in participants
    ]
    await sync_to_async(MessageReceipt.objects.bulk_create)(receipts, ignore_conflicts=True)

    # Mark as delivered for online users
    online_user_ids = [uid for uid in participants if any(
        u and u.pk == uid for u in _sessions.values()
    )]
    if online_user_ids:
        now = timezone.now()
        await sync_to_async(
            MessageReceipt.objects.filter(message=message, recipient_id__in=online_user_ids).update
        )(status="delivered", delivered_at=now)

        receipt_payload = {
            "message_id": str(message.pk),
            "conversation_id": str(conv_id),
            "status": "delivered",
            "delivered_at": now.isoformat(),
        }
        await sio.emit("receipt:update", receipt_payload, room=_room(str(conv_id)))


async def _push_unread_counters(conv_id: str, sender):
    from chat.models import Participant
    participants = await sync_to_async(list)(
        Participant.objects.filter(conversation_id=conv_id, left_at__isnull=True)
        .exclude(user=sender).select_related("user")
    )
    for p in participants:
        count = await sync_to_async(p.unread_count)()
        await sio.emit(
            "unread:update",
            {"conversation_id": str(conv_id), "count": count},
            room=_user_room(p.user_id),
        )


# ---------------------------------------------------------------------------
# message:read
# ---------------------------------------------------------------------------

@sio.event
async def message_read(sid, data):
    user = _sessions.get(sid)
    if not user:
        return

    conv_id    = data.get("conversation_id")
    message_id = data.get("message_id")   # read up to this message

    from chat.models import Participant, Message, MessageReceipt
    now = timezone.now()

    # Update participant watermark
    await sync_to_async(
        Participant.objects.filter(conversation_id=conv_id, user=user).update
    )(last_read_at=now)

    # Bulk-update receipts
    await sync_to_async(
        MessageReceipt.objects.filter(
            message__conversation_id=conv_id,
            recipient=user,
            status__in=["sent", "delivered"],
        ).update
    )(status="read", read_at=now)

    # Notify sender of read receipt
    if message_id:
        msg = await sync_to_async(Message.objects.select_related("sender").filter(pk=message_id).first)()
        if msg and msg.sender:
            await sio.emit(
                "receipt:update",
                {
                    "message_id": message_id,
                    "conversation_id": conv_id,
                    "status": "read",
                    "read_by": str(user.pk),
                    "read_at": now.isoformat(),
                },
                room=_user_room(str(msg.sender_id)),
            )

    # Reset unread counter for reader
    await sio.emit(
        "unread:update",
        {"conversation_id": str(conv_id), "count": 0},
        to=sid,
    )


# ---------------------------------------------------------------------------
# message:edit / delete
# ---------------------------------------------------------------------------

@sio.event
async def message_edit(sid, data):
    user = _sessions.get(sid)
    if not user:
        return await _emit_error(sid, "UNAUTHENTICATED")
    from chat.models import Message
    msg = await sync_to_async(Message.objects.filter(pk=data.get("message_id"), sender=user).first)()
    if not msg:
        return await _emit_error(sid, "NOT_FOUND")
    msg.body = data.get("body", msg.body)
    msg.is_edited = True
    await sync_to_async(msg.save)(update_fields=["body", "is_edited", "updated_at"])
    from chat.serializers import MessageSerializer
    payload = await sync_to_async(lambda: MessageSerializer(msg).data)()
    await sio.emit("message:updated", {"message": dict(payload)}, room=_room(str(msg.conversation_id)))


@sio.event
async def message_delete(sid, data):
    user = _sessions.get(sid)
    if not user:
        return await _emit_error(sid, "UNAUTHENTICATED")
    from chat.models import Message
    msg = await sync_to_async(Message.objects.filter(pk=data.get("message_id"), sender=user).first)()
    if not msg:
        return await _emit_error(sid, "NOT_FOUND")
    await sync_to_async(msg.soft_delete)()
    await sio.emit(
        "message:updated",
        {"message": {"id": str(msg.pk), "is_deleted": True, "conversation_id": str(msg.conversation_id)}},
        room=_room(str(msg.conversation_id)),
    )


# ---------------------------------------------------------------------------
# typing indicators
# ---------------------------------------------------------------------------

@sio.event
async def typing_start(sid, data):
    user = _sessions.get(sid)
    if not user:
        return
    conv_id = data.get("conversation_id")
    await sio.emit(
        "presence:change",
        {"user_id": str(user.pk), "status": "typing", "conversation_id": conv_id},
        room=_room(conv_id),
        skip_sid=sid,
    )


@sio.event
async def typing_stop(sid, data):
    user = _sessions.get(sid)
    if not user:
        return
    conv_id = data.get("conversation_id")
    is_online = user.is_online
    await sio.emit(
        "presence:change",
        {"user_id": str(user.pk), "status": "online" if is_online else "offline", "conversation_id": conv_id},
        room=_room(conv_id),
        skip_sid=sid,
    )


# ---------------------------------------------------------------------------
# reaction:add / remove
# ---------------------------------------------------------------------------

@sio.event
async def reaction_add(sid, data):
    user = _sessions.get(sid)
    if not user:
        return await _emit_error(sid, "UNAUTHENTICATED")
    from chat.models import Reaction, Message
    msg = await sync_to_async(Message.objects.filter(pk=data.get("message_id")).first)()
    if not msg:
        return await _emit_error(sid, "NOT_FOUND")
    reaction, _ = await sync_to_async(Reaction.objects.get_or_create)(
        message=msg, user=user, emoji=data.get("emoji", "👍")
    )
    await sio.emit(
        "reaction:update",
        {
            "message_id": str(msg.pk),
            "conversation_id": str(msg.conversation_id),
            "user_id": str(user.pk),
            "emoji": reaction.emoji,
            "action": "add",
        },
        room=_room(str(msg.conversation_id)),
    )


@sio.event
async def reaction_remove(sid, data):
    user = _sessions.get(sid)
    if not user:
        return
    from chat.models import Reaction
    await sync_to_async(
        Reaction.objects.filter(
            message_id=data.get("message_id"), user=user, emoji=data.get("emoji")
        ).delete
    )()
    await sio.emit(
        "reaction:update",
        {
            "message_id": data.get("message_id"),
            "user_id": str(user.pk),
            "emoji": data.get("emoji"),
            "action": "remove",
        },
        room=_room(str(data.get("conversation_id", ""))),
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

async def _emit_error(sid, code: str, message: str = ""):
    await sio.emit("error", {"code": code, "message": message}, to=sid)


# ---------------------------------------------------------------------------
# ASGI app wrapper — mount under /socket.io/
# ---------------------------------------------------------------------------
socket_app = socketio.ASGIApp(sio, socketio_path="/socket.io")