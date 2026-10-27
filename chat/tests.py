import pytest
from django.db import DataError, IntegrityError, transaction
from django.urls import reverse

from .models import Conversation, ConversationKind, Membership, Message

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice", first_name="alice", password="pw"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="bob", first_name="bob", password="pw"
    )


@pytest.fixture
def channel(alice):
    return Conversation.objects.create(
        kind=ConversationKind.CHANNEL, name="general", created_by=alice
    )


def make_dm(created_by, dm_key="1:2", **extra):
    return Conversation.objects.create(
        kind=ConversationKind.DIRECT, dm_key=dm_key, created_by=created_by, **extra
    )


def assert_rejected(create, error=IntegrityError):
    with pytest.raises(error), transaction.atomic():
        create()


# Conversation shape


def test_channel_and_dm_can_be_created(channel, alice):
    dm = make_dm(alice)
    assert str(channel) == "#general"
    assert str(dm) == "DM 1:2"


def test_unknown_kind_is_rejected(alice):
    assert_rejected(
        lambda: Conversation.objects.create(kind="group", name="x", created_by=alice)
    )


def test_channel_needs_a_name(alice):
    assert_rejected(
        lambda: Conversation.objects.create(
            kind=ConversationKind.CHANNEL, created_by=alice
        )
    )


def test_channel_cannot_have_a_dm_key(alice):
    assert_rejected(
        lambda: Conversation.objects.create(
            kind=ConversationKind.CHANNEL, name="x", dm_key="1:2", created_by=alice
        )
    )


def test_dm_needs_a_dm_key(alice):
    assert_rejected(lambda: make_dm(alice, dm_key=""))


def test_dm_cannot_have_a_name(alice):
    assert_rejected(lambda: make_dm(alice, name="secret"))


def test_dm_cannot_be_flagged_private(alice):
    assert_rejected(lambda: make_dm(alice, is_private=True))


# Uniqueness


def test_channel_names_are_unique_ignoring_case(channel, alice):
    assert_rejected(
        lambda: Conversation.objects.create(
            kind=ConversationKind.CHANNEL, name="General", created_by=alice
        )
    )


def test_only_one_dm_per_pair(alice):
    make_dm(alice)
    assert_rejected(lambda: make_dm(alice))


def test_person_joins_a_conversation_only_once(channel, bob):
    Membership.objects.create(conversation=channel, user=bob)
    assert_rejected(lambda: Membership.objects.create(conversation=channel, user=bob))


# Messages


def test_message_can_be_posted(channel, alice):
    message = Message.objects.create(conversation=channel, author=alice, body="hi")
    assert list(channel.messages.all()) == [message]


@pytest.mark.parametrize("body", ["", "   ", "\n\t"])
def test_blank_message_is_rejected(channel, alice, body):
    assert_rejected(
        lambda: Message.objects.create(conversation=channel, author=alice, body=body)
    )


def test_message_longer_than_4000_characters_is_rejected(channel, alice):
    assert_rejected(
        lambda: Message.objects.create(
            conversation=channel, author=alice, body="x" * 4001
        ),
        error=DataError,
    )


def test_deleting_a_conversation_removes_its_messages(channel, alice):
    Message.objects.create(conversation=channel, author=alice, body="hi")
    channel.delete()
    assert not Message.objects.exists()


# History


def test_conversation_and_membership_changes_are_recorded(channel, bob):
    channel.name = "announcements"
    channel.save()
    Membership.objects.create(conversation=channel, user=bob)

    assert channel.history.count() == 2
    assert channel.history.first().name == "announcements"
    assert Membership.history.count() == 1


# Admin


def test_admin_conversation_list_loads(admin_client, channel):
    response = admin_client.get(reverse("admin:chat_conversation_changelist"))
    assert response.status_code == 200


def test_superadmin_can_add_messages(admin_client):
    response = admin_client.get(reverse("admin:chat_message_add"))
    assert response.status_code == 200
