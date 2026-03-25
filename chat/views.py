"""
REST API endpoints for conversation and message management.
All real-time delivery happens via Socket.IO (sio_server.py).
These endpoints serve: auth, history pagination, file uploads, search.
"""

import mimetypes

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import parsers, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Attachment, Conversation, Message, Participant
from .serializers import (
    AttachmentSerializer,
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
    MessageSerializer,
)

User = get_user_model()


class ConversationListCreateAPIView(APIView):
    """
    GET  /api/chat/conversations/  — inbox list (ordered by latest activity)
    POST /api/chat/conversations/  — create DM or group
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        conversations = (
            Conversation.objects.filter(
                participants__user=request.user,
                participants__left_at__isnull=True,
            )
            .prefetch_related("participants__user", "messages")
            .order_by("-updated_at")
            .distinct()
        )
        serializer = ConversationListSerializer(
            conversations,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data["type"] == "direct":
            other_id = data["user_ids"][0]
            existing = (
                Conversation.objects.filter(type="direct")
                .filter(participants__user=request.user, participants__left_at__isnull=True)
                .filter(participants__user_id=other_id, participants__left_at__isnull=True)
                .distinct()
                .first()
            )
            if existing:
                detail_serializer = ConversationDetailSerializer(
                    existing,
                    context={"request": request},
                )
                return Response(detail_serializer.data, status=status.HTTP_200_OK)

        with transaction.atomic():
            conversation = Conversation.objects.create(
                type=data["type"],
                name=data.get("name", ""),
                description=data.get("description", ""),
                created_by=request.user,
            )

            all_user_ids = list(set(data["user_ids"] + [request.user.pk]))
            participants = []
            for uid in all_user_ids:
                role = "admin" if uid == request.user.pk else "member"
                participants.append(
                    Participant(
                        conversation=conversation,
                        user_id=uid,
                        role=role,
                    )
                )
            Participant.objects.bulk_create(participants)

            Message.objects.create(
                conversation=conversation,
                sender=request.user,
                message_type="system",
                body=f"Conversation created by {request.user.username or request.user.email}",
            )

        detail_serializer = ConversationDetailSerializer(
            conversation,
            context={"request": request},
        )
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)


class ConversationDetailAPIView(APIView):
    """
    GET    /api/chat/conversations/<id>/  — full conversation + last 50 msgs
    PATCH  /api/chat/conversations/<id>/  — update name/avatar (group admin)
    DELETE /api/chat/conversations/<id>/  — soft-leave / archive
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, request, pk):
        conversation = (
            Conversation.objects.filter(
                participants__user=request.user,
                participants__left_at__isnull=True,
            )
            .prefetch_related("participants__user", "messages")
            .filter(pk=pk)
            .first()
        )
        if not conversation:
            raise NotFound("Conversation not found")
        return conversation

    def get(self, request, pk):
        conversation = self.get_object(request, pk)
        serializer = ConversationDetailSerializer(
            conversation,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        conversation = self.get_object(request, pk)

        admin_exists = Participant.objects.filter(
            conversation=conversation,
            user=request.user,
            role="admin",
            left_at__isnull=True,
        ).exists()
        if not admin_exists:
            raise PermissionDenied("Admin access required")

        if conversation.type != "group":
            raise ValidationError({"detail": "Only group conversations can be updated"})

        allowed_fields = ["name", "description"]
        update_fields = []

        for field in allowed_fields:
            if field in request.data:
                setattr(conversation, field, request.data.get(field))
                update_fields.append(field)

        if update_fields:
            update_fields.append("updated_at")
            conversation.save(update_fields=update_fields)

        serializer = ConversationDetailSerializer(
            conversation,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        conversation = self.get_object(request, pk)
        Participant.objects.filter(
            conversation=conversation,
            user=request.user,
            left_at__isnull=True,
        ).update(
            left_at=timezone.now(),
            is_archived=True,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessageListAPIView(APIView):
    """
    GET /api/chat/conversations/<conv_id>/messages/?before=<uuid>&limit=50
    Cursor-style pagination for infinite scroll.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _assert_participant(self, request, conv_id):
        exists = Participant.objects.filter(
            conversation_id=conv_id,
            user=request.user,
            left_at__isnull=True,
        ).exists()
        if not exists:
            raise PermissionDenied("Not a participant")

    def get(self, request, conv_id):
        self._assert_participant(request, conv_id)

        queryset = Message.objects.filter(
            conversation_id=conv_id,
            is_deleted=False,
        ).select_related("sender").prefetch_related(
            "attachments",
            "reactions",
            "receipts",
        )

        before = request.query_params.get("before")
        if before:
            try:
                pivot = Message.objects.get(pk=before, conversation_id=conv_id)
                queryset = queryset.filter(created_at__lt=pivot.created_at)
            except Message.DoesNotExist:
                pass

        limit_raw = request.query_params.get("limit", "50")
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ValidationError({"limit": "limit must be an integer"})

        if limit <= 0:
            raise ValidationError({"limit": "limit must be greater than 0"})

        limit = min(limit, 100)

        messages = list(queryset.order_by("-created_at")[:limit])
        messages.reverse()

        serializer = MessageSerializer(messages, many=True)
        has_more = len(messages) == limit

        next_before = str(messages[0].id) if messages else None

        return Response(
            {
                "messages": serializer.data,
                "count": len(serializer.data),
                "limit": limit,
                "has_more": has_more,
                "next_before": next_before,
            },
            status=status.HTTP_200_OK,
        )


class AttachmentUploadAPIView(APIView):
    """
    POST /api/chat/messages/<message_id>/attachments/
    Multipart file upload; returns attachment data to embed in the message.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

    def post(self, request, message_id):
        try:
            message = Message.objects.get(pk=message_id, sender=request.user)
        except Message.DoesNotExist:
            raise NotFound("Message not found")

        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "No file provided"})

        if upload.size > self.MAX_FILE_SIZE:
            raise ValidationError({"file": "File too large (max 50 MB)"})

        mime, _ = mimetypes.guess_type(upload.name)
        mime = mime or "application/octet-stream"
        attachment_type = self._classify(mime)

        attachment = Attachment.objects.create(
            message=message,
            uploaded_by=request.user,
            attachment_type=attachment_type,
            file=upload,
            file_name=upload.name,
            file_size=upload.size,
            mime_type=mime,
        )

        serializer = AttachmentSerializer(attachment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _classify(mime: str) -> str:
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("audio/"):
            return "audio"
        if mime in ("application/pdf", "text/plain"):
            return "document"
        return "other"


class ParticipantManageAPIView(APIView):
    """
    POST   /api/chat/conversations/<conv_id>/participants/  — add member
    DELETE /api/chat/conversations/<conv_id>/participants/<user_id>/  — remove member
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_conv_as_admin(self, request, conv_id):
        participant = (
            Participant.objects.filter(
                conversation_id=conv_id,
                user=request.user,
                role="admin",
                left_at__isnull=True,
            )
            .select_related("conversation")
            .first()
        )
        if not participant:
            raise PermissionDenied("Admin access required")
        return participant.conversation

    def post(self, request, conv_id):
        conversation = self._get_conv_as_admin(request, conv_id)

        user_id = request.data.get("user_id")
        if not user_id:
            raise ValidationError({"user_id": "user_id is required"})

        participant, created = Participant.objects.get_or_create(
            conversation=conversation,
            user_id=user_id,
            defaults={"role": "member"},
        )

        if not created and participant.left_at:
            participant.left_at = None
            participant.is_archived = False
            participant.save(update_fields=["left_at", "is_archived"])

        return Response({"status": "added"}, status=status.HTTP_200_OK)

    def delete(self, request, conv_id, user_id):
        conversation = self._get_conv_as_admin(request, conv_id)

        updated = Participant.objects.filter(
            conversation=conversation,
            user_id=user_id,
            left_at__isnull=True,
        ).update(left_at=timezone.now())

        if not updated:
            raise NotFound("Participant not found")

        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationSearchAPIView(APIView):
    """
    GET /api/chat/search/?q=<query>
    Search across messages user has access to.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return Response(
                {
                    "messages": [],
                    "count": 0,
                    "query": query,
                },
                status=status.HTTP_200_OK,
            )

        user_conversation_ids = Participant.objects.filter(
            user=request.user,
            left_at__isnull=True,
        ).values_list("conversation_id", flat=True)

        messages = (
            Message.objects.filter(
                conversation_id__in=user_conversation_ids,
                body__icontains=query,
                is_deleted=False,
            )
            .select_related("sender")
            .prefetch_related("attachments", "reactions", "receipts")
            .order_by("-created_at")[:100]
        )

        serializer = MessageSerializer(messages, many=True)
        return Response(
            {
                "messages": serializer.data,
                "count": len(serializer.data),
                "query": query,
            },
            status=status.HTTP_200_OK,
        )