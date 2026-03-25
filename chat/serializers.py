# chat/serializers.py

from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Conversation, Participant, Message,
    Attachment, MessageReceipt, Reaction,
)

User = get_user_model()


class UserMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["user_id", "username", "email", "is_online", "last_activity"]


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = [
            "id", "attachment_type", "file", "file_name",
            "file_size", "mime_type", "thumbnail", "width", "height", "duration",
        ]


class ReactionSerializer(serializers.ModelSerializer):
    user = UserMinimalSerializer(read_only=True)

    class Meta:
        model = Reaction
        fields = ["id", "user", "emoji", "created_at"]


class MessageReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageReceipt
        fields = ["recipient_id", "status", "delivered_at", "read_at"]


class MessageSerializer(serializers.ModelSerializer):
    sender        = UserMinimalSerializer(read_only=True)
    attachments   = AttachmentSerializer(many=True, read_only=True)
    reactions     = ReactionSerializer(many=True, read_only=True)
    receipts      = MessageReceiptSerializer(many=True, read_only=True)
    reply_to      = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id", "conversation", "sender", "message_type", "body",
            "reply_to", "client_message_id",
            "is_edited", "is_deleted",
            "attachments", "reactions", "receipts",
            "created_at", "updated_at",
        ]

    def get_reply_to(self, obj):
        if obj.reply_to_id:
            return {
                "id": str(obj.reply_to_id),
                "body": obj.reply_to.body if obj.reply_to and not obj.reply_to.is_deleted else None,
                "sender_id": str(obj.reply_to.sender_id) if obj.reply_to else None,
            }
        return None


class ParticipantSerializer(serializers.ModelSerializer):
    user         = UserMinimalSerializer(read_only=True)
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Participant
        fields = ["id", "user", "role", "nickname", "unread_count", "is_muted", "joined_at"]

    def get_unread_count(self, obj):
        return obj.unread_count()


class ConversationListSerializer(serializers.ModelSerializer):
    participants  = ParticipantSerializer(many=True, read_only=True)
    last_message  = serializers.SerializerMethodField()
    display_name  = serializers.SerializerMethodField()
    unread_count  = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "type", "name", "avatar", "description", "display_name",
            "participants", "last_message", "unread_count",
            "created_by_id", "created_at", "updated_at",
        ]

    def get_display_name(self, obj):
        request = self.context.get("request")
        if request:
            return obj.get_display_name(request.user)
        return obj.name or str(obj.id)

    def get_last_message(self, obj):
        msg = obj.messages.filter(is_deleted=False).order_by("-created_at").first()
        if msg:
            return MessageSerializer(msg).data
        return None

    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request:
            return 0
        p = obj.participants.filter(user=request.user).first()
        return p.unread_count() if p else 0


class ConversationDetailSerializer(ConversationListSerializer):
    """Full conversation including paginated messages (latest 50)."""
    messages = serializers.SerializerMethodField()

    class Meta(ConversationListSerializer.Meta):
        fields = ConversationListSerializer.Meta.fields + ["messages"]

    def get_messages(self, obj):
        msgs = obj.messages.filter(is_deleted=False).order_by("-created_at")[:50]
        return MessageSerializer(reversed(list(msgs)), many=True).data


# ---------------------------------------------------------------------------
# Write serializers
# ---------------------------------------------------------------------------

class ConversationCreateSerializer(serializers.Serializer):
    type        = serializers.ChoiceField(choices=["direct", "group"])
    name        = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    user_ids    = serializers.ListField(
        child=serializers.IntegerField(), min_length=1,
        help_text="IDs of users to add (excluding self)"
    )

    def validate(self, data):
        if data["type"] == "direct" and len(data["user_ids"]) != 1:
            raise serializers.ValidationError("Direct conversations require exactly 1 other user.")
        if data["type"] == "group" and not data.get("name"):
            raise serializers.ValidationError("Group conversations require a name.")
        return data


class MessageCreateSerializer(serializers.Serializer):
    conversation_id   = serializers.UUIDField()
    body              = serializers.CharField(required=False, allow_blank=True)
    message_type      = serializers.ChoiceField(choices=["text","image","video","audio","file"], default="text")
    reply_to_id       = serializers.UUIDField(required=False, allow_null=True)
    client_message_id = serializers.CharField(max_length=100, required=False, allow_blank=True)