#chat/models.py

import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Conversation(models.Model):
    CONVERSATION_TYPE = (
        ("direct", "Direct Message"),
        ("group", "Group Chat"),
    )

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type        = models.CharField(max_length=10, choices=CONVERSATION_TYPE, default="direct")
    name        = models.CharField(max_length=255, blank=True, null=True)        # for groups
    avatar      = models.ImageField(upload_to="conversations/avatars/", null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="created_conversations",
        on_delete=models.SET_NULL, null=True
    )
    created_at  = models.DateTimeField(default=timezone.now)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["type"]),
            models.Index(fields=["updated_at"]),
        ]

    def __str__(self):
        return f"{self.type} | {self.id}"

    def get_display_name(self, requesting_user):
        """For DMs, return the other participant's name."""
        if self.type == "group":
            return self.name or "Unnamed Group"
        other = self.participants.exclude(user=requesting_user).select_related("user").first()
        if other:
            return other.user.username or other.user.email or "Unknown"
        return "Unknown"


class Participant(models.Model):
    ROLE_CHOICES = (
        ("admin", "Admin"),
        ("member", "Member"),
    )

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, related_name="participants", on_delete=models.CASCADE)
    user         = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="participations", on_delete=models.CASCADE)
    role         = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    nickname     = models.CharField(max_length=100, blank=True, null=True)
    last_read_at = models.DateTimeField(null=True, blank=True)   # watermark for unread counter
    is_muted     = models.BooleanField(default=False)
    is_archived  = models.BooleanField(default=False)
    joined_at    = models.DateTimeField(default=timezone.now)
    left_at      = models.DateTimeField(null=True, blank=True)   # soft-leave for groups

    class Meta:
        unique_together = ("conversation", "user")
        indexes = [
            models.Index(fields=["user", "conversation"]),
            models.Index(fields=["last_read_at"]),
        ]

    def __str__(self):
        return f"{self.user} in {self.conversation}"

    def unread_count(self):
        if not self.last_read_at:
            return self.conversation.messages.filter(is_deleted=False).count()
        return self.conversation.messages.filter(
            created_at__gt=self.last_read_at, is_deleted=False
        ).exclude(sender=self.user).count()


class Message(models.Model):
    """
    Core message entity. Supports text, attachments, replies, reactions,
    idempotency via client_message_id, and soft-delete.
    """
    MESSAGE_TYPES = (
        ("text",     "Text"),
        ("image",    "Image"),
        ("video",    "Video"),
        ("audio",    "Audio"),
        ("file",     "File"),
        ("system",   "System"),   # e.g., "User X joined"
    )

    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation      = models.ForeignKey(Conversation, related_name="messages", on_delete=models.CASCADE)
    sender            = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="sent_messages",
        on_delete=models.SET_NULL, null=True
    )
    message_type      = models.CharField(max_length=10, choices=MESSAGE_TYPES, default="text")
    body              = models.TextField(blank=True, null=True)
    reply_to          = models.ForeignKey(
        "self", null=True, blank=True, related_name="replies", on_delete=models.SET_NULL
    )
    # Idempotency — client generates a unique ID per send attempt; server deduplicates
    client_message_id = models.CharField(max_length=100, db_index=True, blank=True, null=True)
    is_edited         = models.BooleanField(default=False)
    is_deleted        = models.BooleanField(default=False)
    deleted_at        = models.DateTimeField(null=True, blank=True)
    created_at        = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["sender"]),
            models.Index(fields=["client_message_id"]),
        ]

    def __str__(self):
        return f"[{self.message_type}] {self.sender} → {self.conversation}"

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.body = None
        self.save(update_fields=["is_deleted", "deleted_at", "body", "updated_at"])


class Attachment(models.Model):
    """
    File / media attached to a message.
    """
    ATTACHMENT_TYPES = (
        ("image", "Image"),
        ("video", "Video"),
        ("audio", "Audio"),
        ("document", "Document"),
        ("other", "Other"),
    )

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message         = models.ForeignKey(Message, related_name="attachments", on_delete=models.CASCADE)
    uploaded_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    attachment_type = models.CharField(max_length=10, choices=ATTACHMENT_TYPES, default="other")
    file            = models.FileField(upload_to="chat/attachments/%Y/%m/%d/")
    file_name       = models.CharField(max_length=255)
    file_size       = models.PositiveBigIntegerField(help_text="Size in bytes")
    mime_type       = models.CharField(max_length=100, blank=True)
    thumbnail       = models.ImageField(upload_to="chat/thumbnails/", null=True, blank=True)
    width           = models.PositiveIntegerField(null=True, blank=True)   # for images/videos
    height          = models.PositiveIntegerField(null=True, blank=True)
    duration        = models.FloatField(null=True, blank=True)             # for audio/video in seconds
    created_at      = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["message"])]


class MessageReceipt(models.Model):
    """
    Delivery & read receipts per recipient.
    Two-tick system: delivered + read (like WhatsApp).
    """
    STATUS_CHOICES = (
        ("sent",      "Sent"),
        ("delivered", "Delivered"),
        ("read",      "Read"),
    )

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message      = models.ForeignKey(Message, related_name="receipts", on_delete=models.CASCADE)
    recipient    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default="sent")
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("message", "recipient")
        indexes = [
            models.Index(fields=["message", "status"]),
            models.Index(fields=["recipient", "status"]),
        ]


class Reaction(models.Model):
    """
    Emoji reactions on messages.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message    = models.ForeignKey(Message, related_name="reactions", on_delete=models.CASCADE)
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    emoji      = models.CharField(max_length=10)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("message", "user", "emoji")

    def __str__(self):
        return f"{self.user} reacted {self.emoji} on {self.message}"


class PresenceLog(models.Model):
    """
    Audit log of user online/offline events for observability.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="presence_logs")
    event      = models.CharField(max_length=20)   # "connect", "disconnect", "typing_start", etc.
    socket_id  = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp  = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["user", "timestamp"])]