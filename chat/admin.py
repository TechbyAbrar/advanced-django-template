# chat/admin.py
from django.contrib import admin
from .models import (
    Conversation, Participant, Message,
    Attachment, MessageReceipt, Reaction, PresenceLog
)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display  = ["id", "type", "name", "created_by", "created_at", "updated_at"]
    list_filter   = ["type"]
    search_fields = ["name", "id"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display  = ["user", "conversation", "role", "joined_at", "left_at"]
    list_filter   = ["role"]
    search_fields = ["user__email", "user__username"]
    raw_id_fields = ["user", "conversation"]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display  = ["id", "conversation", "sender", "message_type", "is_deleted", "created_at"]
    list_filter   = ["message_type", "is_deleted"]
    search_fields = ["body", "sender__email"]
    raw_id_fields = ["sender", "conversation"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ["id", "message", "attachment_type", "file_name", "file_size", "created_at"]
    list_filter  = ["attachment_type"]


@admin.register(MessageReceipt)
class MessageReceiptAdmin(admin.ModelAdmin):
    list_display = ["message", "recipient", "status", "delivered_at", "read_at"]
    list_filter  = ["status"]


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ["message", "user", "emoji", "created_at"]


@admin.register(PresenceLog)
class PresenceLogAdmin(admin.ModelAdmin):
    list_display  = ["user", "event", "socket_id", "ip_address", "timestamp"]
    list_filter   = ["event"]
    search_fields = ["user__email", "socket_id"]
    readonly_fields = ["id", "timestamp"]