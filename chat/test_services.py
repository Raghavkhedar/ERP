import pytest
from django.utils import timezone

from .models import Conversation, ConversationKind, Membership
from .services import conversation_title, visible_conversations

pytestmark = pytest.mark.django_db


def make_channel(name, created_by, members=(), is_private=False):
    channel = Conversation.objects.create(
        kind=ConversationKind.CHANNEL,
        name=name,
        is_private=is_private,
        created_by=created_by,
    )
    for user in members:
        Membership.objects.create(conversation=channel, user=user)
    return channel


def make_dm(a, b):
    low, high = sorted([a.id, b.id])
    dm = Conversation.objects.create(
        kind=ConversationKind.DIRECT, dm_key=f"{low}:{high}", created_by=a
    )
    Membership.objects.create(conversation=dm, user=a)
    if b != a:
        Membership.objects.create(conversation=dm, user=b)
    return dm


def test_public_channel_is_visible_to_everyone(alice, bob):
    general = make_channel("general", alice, members=[alice])
    assert general in visible_conversations(bob)


def test_private_channel_is_hidden_from_non_members(alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    assert secret not in visible_conversations(bob)


def test_private_channel_is_visible_to_members(alice, bob):
    secret = make_channel("secret", alice, members=[alice, bob], is_private=True)
    assert secret in visible_conversations(bob)


def test_dm_is_visible_only_to_its_two_people(alice, bob, carol):
    dm = make_dm(alice, bob)
    assert dm in visible_conversations(alice)
    assert dm in visible_conversations(bob)
    assert dm not in visible_conversations(carol)


def test_member_of_public_channel_sees_it_once(alice):
    make_channel("general", alice, members=[alice])
    assert visible_conversations(alice).count() == 1


def test_archived_conversations_are_hidden(alice):
    general = make_channel("general", alice, members=[alice])
    general.archived_at = timezone.now()
    general.save()
    assert general not in visible_conversations(alice)


def test_channel_title_has_a_hash(alice):
    general = make_channel("general", alice)
    assert conversation_title(general, alice) == "#general"


def test_dm_title_is_the_other_persons_name(alice, bob):
    dm = make_dm(alice, bob)
    assert conversation_title(dm, alice) == "bob"
    assert conversation_title(dm, bob) == "alice"


def test_dm_with_yourself_is_titled_with_your_name(alice):
    dm = make_dm(alice, alice)
    assert conversation_title(dm, alice) == "alice"
