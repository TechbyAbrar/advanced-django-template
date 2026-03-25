from django.urls import path

from .views import (
    AttachmentUploadAPIView,
    ConversationDetailAPIView,
    ConversationListCreateAPIView,
    ConversationSearchAPIView,
    MessageListAPIView,
    ParticipantManageAPIView,
)

urlpatterns = [
    path(
        "conversations/",
        ConversationListCreateAPIView.as_view(),
        name="conversation-list-create",
    ),
    path(
        "conversations/<uuid:pk>/",
        ConversationDetailAPIView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<uuid:conv_id>/messages/",
        MessageListAPIView.as_view(),
        name="message-list",
    ),
    path(
        "messages/<uuid:message_id>/attachments/",
        AttachmentUploadAPIView.as_view(),
        name="attachment-upload",
    ),
    path(
        "conversations/<uuid:conv_id>/participants/",
        ParticipantManageAPIView.as_view(),
        name="participant-add",
    ),
    path(
        "conversations/<uuid:conv_id>/participants/<int:user_id>/",
        ParticipantManageAPIView.as_view(),
        name="participant-remove",
    ),
    path(
        "search/",
        ConversationSearchAPIView.as_view(),
        name="message-search",
    ),
]