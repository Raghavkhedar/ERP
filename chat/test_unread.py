import pytest

from .models import Membership, Message
from .services import mark_read, unread_counts
from .test_services import make_channel, make_dm

pytestmark = pytest.mark.django_db


def post(conversation, author, body="hi"):
    return Message.objects.create(conversation=conversation, author=author, body=body)


def test_messages_from_others_are_unread_until_marked_read(alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    post(general, alice)
    post(general, alice)

    assert unread_counts(bob) == {general.pk: 2}

    mark_read(general, bob)

    assert unread_counts(bob) == {}


def test_own_messages_never_count_as_unread(alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    post(general, alice)
    assert unread_counts(alice) == {}


def test_only_messages_after_the_marker_count(alice, bob):
    dm = make_dm(alice, bob)
    post(dm, alice, "old")
    mark_read(dm, bob)
    post(dm, alice, "new")
    assert unread_counts(bob) == {dm.pk: 1}


def test_counts_are_per_conversation(alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    random = make_channel("random", alice, members=[alice, bob])
    post(general, alice)
    post(random, alice)
    post(random, alice)
    assert unread_counts(bob) == {general.pk: 1, random.pk: 2}


def test_non_members_have_no_unread(alice, bob):
    general = make_channel("general", alice, members=[alice])
    post(general, alice)
    assert unread_counts(bob) == {}


def test_marker_never_moves_backwards(alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    post(general, alice)
    newest = post(general, alice)
    membership = Membership.objects.get(conversation=general, user=bob)
    Membership.objects.filter(pk=membership.pk).update(last_read_message=newest)

    mark_read(general, bob)  # nothing newer, so nothing changes

    membership.refresh_from_db()
    assert membership.last_read_message == newest


def test_marking_read_in_an_empty_conversation_does_nothing(alice):
    general = make_channel("general", alice, members=[alice])
    mark_read(general, alice)
    assert Membership.objects.get().last_read_message is None


def test_marking_read_adds_no_history(alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    post(general, alice)
    membership = Membership.objects.get(conversation=general, user=bob)
    before = membership.history.count()

    mark_read(general, bob)

    assert membership.history.count() == before
