from django.db.models import Count, Max, Q
from django.db.models.functions import Coalesce

from .models import Conversation, ConversationKind, Membership


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


def mark_read(conversation, user):
    """Move the user's read marker up to the newest message, never back."""
    newest = conversation.messages.aggregate(newest=Max("id"))["newest"]
    if newest is None:
        return
    Membership.objects.filter(conversation=conversation, user=user).filter(
        Q(last_read_message__isnull=True) | Q(last_read_message__lt=newest)
    ).update(last_read_message=newest)


def unread_counts(user):
    """{conversation id: unread messages from other people}, zeros left out."""
    memberships = Membership.objects.filter(user=user).annotate(
        unread=Count(
            "conversation__messages",
            filter=Q(conversation__messages__id__gt=Coalesce("last_read_message", 0))
            & ~Q(conversation__messages__author=user),
        )
    )
    return {m.conversation_id: m.unread for m in memberships if m.unread}
