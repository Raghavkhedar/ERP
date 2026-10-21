from django.db import transaction
from django.db.models import Count, Max, Q
from django.db.models.functions import Coalesce

from .models import Conversation, ConversationKind, Membership, Message, MessageKind


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


@transaction.atomic
def join(conversation, user):
    """Make the user a member and announce it. Joining twice does nothing."""
    _, created = Membership.objects.get_or_create(conversation=conversation, user=user)
    if created:
        Message.objects.create(
            conversation=conversation,
            author=user,
            kind=MessageKind.SYSTEM,
            body="joined the channel",
        )


def can_add_people(conversation, user):
    """Only a private channel's creator and Office admins add its members."""
    if conversation.kind != ConversationKind.CHANNEL or not conversation.is_private:
        return False
    return (
        conversation.created_by_id == user.pk
        or user.is_superuser
        or user.groups.filter(name="Office admin").exists()
    )


@transaction.atomic
def add_member(conversation, added_by, user):
    """Add someone and announce it. Adding a member twice does nothing."""
    _, created = Membership.objects.get_or_create(conversation=conversation, user=user)
    if created:
        Message.objects.create(
            conversation=conversation,
            author=added_by,
            kind=MessageKind.SYSTEM,
            body=f"added {user.username}",
        )


@transaction.atomic
def create_channel(user, name, is_private):
    """A new channel with its creator as the first member."""
    channel = Conversation.objects.create(
        kind=ConversationKind.CHANNEL,
        name=name,
        is_private=is_private,
        created_by=user,
    )
    Membership.objects.create(conversation=channel, user=user)
    Message.objects.create(
        conversation=channel,
        author=user,
        kind=MessageKind.SYSTEM,
        body="created the channel",
    )
    return channel


@transaction.atomic
def get_or_create_dm(user, other):
    """The DM between two people, created with both memberships if new."""
    low, high = sorted([user.pk, other.pk])
    dm, created = Conversation.objects.get_or_create(
        kind=ConversationKind.DIRECT,
        dm_key=f"{low}:{high}",
        defaults={"created_by": user},
    )
    if created:
        for person in {user, other}:
            Membership.objects.create(conversation=dm, user=person)
    return dm


@transaction.atomic
def post_notice(author, recipient, body):
    """An automatic message in their DM that counts as unread for the recipient."""
    dm = get_or_create_dm(author, recipient)
    return Message.objects.create(
        conversation=dm, author=author, kind=MessageKind.NOTICE, body=body
    )


def mark_read(conversation, user):
    """Move the user's read marker up to the newest message, never back."""
    newest = conversation.messages.aggregate(newest=Max("id"))["newest"]
    if newest is None:
        return
    Membership.objects.filter(conversation=conversation, user=user).filter(
        Q(last_read_message__isnull=True) | Q(last_read_message__lt=newest)
    ).update(last_read_message=newest)


def unread_counts(user):
    """{conversation id: unread messages from other people}, zeros left out.

    System messages, such as "joined the channel", never count.
    """
    memberships = Membership.objects.filter(user=user).annotate(
        unread=Count(
            "conversation__messages",
            filter=Q(conversation__messages__id__gt=Coalesce("last_read_message", 0))
            & ~Q(conversation__messages__author=user)
            & ~Q(conversation__messages__kind=MessageKind.SYSTEM),
        )
    )
    return {m.conversation_id: m.unread for m in memberships if m.unread}
