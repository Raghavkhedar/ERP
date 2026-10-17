from django.db.models import Q

from .models import Conversation, ConversationKind


def visible_conversations(user):
    """Conversations the user may open: their own, plus public channels."""
    is_member = Q(memberships__user=user)
    is_public_channel = Q(kind=ConversationKind.CHANNEL, is_private=False)
    return (
        Conversation.objects.filter(is_member | is_public_channel)
        .filter(archived_at__isnull=True)
        .distinct()
    )


def conversation_title(conversation, viewer):
    """'#name' for a channel; the other person's username for a DM."""
    if conversation.kind == ConversationKind.CHANNEL:
        return f"#{conversation.name}"
    others = [m.user for m in conversation.memberships.all() if m.user_id != viewer.id]
    return others[0].username if others else viewer.username


def is_member(conversation, user):
    return conversation.memberships.filter(user=user).exists()
