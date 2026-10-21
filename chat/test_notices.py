import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from .models import Conversation, ConversationKind, Message
from .services import mark_read, post_notice, unread_counts

pytestmark = pytest.mark.django_db


def test_notice_goes_into_the_dm_between_the_two(alice, bob):
    message = post_notice(alice, bob, "booked your slot")

    dm = Conversation.objects.get()
    assert dm.kind == ConversationKind.DIRECT
    assert message.conversation == dm
    assert message.author == alice
    assert message.is_notice
    assert not message.is_system


def test_notices_reuse_an_existing_dm(alice, bob):
    post_notice(alice, bob, "first")
    post_notice(bob, alice, "second")
    assert Conversation.objects.count() == 1
    assert Message.objects.count() == 2


def test_notice_counts_as_unread_for_the_recipient_only(alice, bob):
    message = post_notice(alice, bob, "booked your slot")

    assert unread_counts(bob) == {message.conversation_id: 1}
    assert unread_counts(alice) == {}


def test_reading_the_dm_clears_the_notice(alice, bob):
    message = post_notice(alice, bob, "booked your slot")
    mark_read(message.conversation, bob)
    assert unread_counts(bob) == {}


def test_notice_is_shown_highlighted(client, alice, bob):
    message = post_notice(alice, bob, "booked your slot")
    client.force_login(bob)

    url = reverse("chat:conversation_detail", args=[message.conversation_id])
    html = " ".join(client.get(url).content.decode().split())

    assert "alice</span> booked your slot" in html
    assert "bg-amber-50" in html


def test_unknown_kind_is_still_rejected(alice, bob):
    message = post_notice(alice, bob, "x")
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(
            conversation=message.conversation, author=alice, body="y", kind="alert"
        )
