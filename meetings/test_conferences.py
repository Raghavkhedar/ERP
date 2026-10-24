from datetime import datetime, time, timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from chat.models import Message

from .models import Invitation
from .services import (
    SlotError,
    add_invitees,
    book,
    cancel_conference,
    conference_clashes,
    create_conference,
    is_busy,
    remove_invitee,
    respond,
)
from .testing import open_slots

pytestmark = pytest.mark.django_db

DAY = timezone.localdate() + timedelta(days=1)


def at(hour, minute=0):
    return timezone.make_aware(datetime.combine(DAY, time(hour, minute)))


@pytest.fixture
def conference(alice, bob, carol):
    return create_conference(
        alice, "Quarterly review", at(10), at(11), [bob, carol], location="Room 2"
    )


def notices(user):
    return list(
        Message.objects.filter(conversation__memberships__user=user).order_by("id")
    )


def status(conference, user):
    return conference.invitations.get(user=user).status


def test_creating_invites_people_and_tells_them(conference, bob):
    assert conference.invitations.count() == 2
    assert status(conference, bob) == Invitation.Status.INVITED
    [notice] = [m for m in notices(bob) if "Quarterly review" in m.body]
    assert "invited you to Quarterly review" in notice.body
    assert "Room 2" in notice.body


def test_the_host_is_never_an_invitee(alice, bob):
    conference = create_conference(alice, "Sync", at(10), at(11), [alice, bob])
    assert [i.user for i in conference.invitations.all()] == [bob]


@pytest.mark.parametrize(
    "title, start, end",
    [
        ("  ", at(10), at(11)),
        ("Sync", at(11), at(10)),
        ("Sync", at(10), at(10)),
        ("Sync", at(10) - timedelta(days=5), at(11) - timedelta(days=5)),
    ],
)
def test_bad_conferences_are_refused(alice, bob, title, start, end):
    with pytest.raises(SlotError):
        create_conference(alice, title, start, end, [bob])


def test_accepting_and_declining_tell_the_host(conference, alice, bob, carol):
    respond(conference, bob, True)
    respond(conference, carol, False)

    assert status(conference, bob) == Invitation.Status.ACCEPTED
    assert status(conference, carol) == Invitation.Status.DECLINED
    bodies = [m.body for m in notices(alice)]
    assert any("accepted Quarterly review" in b for b in bodies)
    assert any("declined Quarterly review" in b for b in bodies)


def test_only_invitees_can_respond(conference, django_user_model):
    stranger = django_user_model.objects.create_user(username="dan", password="pw")
    with pytest.raises(PermissionDenied):
        respond(conference, stranger, True)


def test_accepted_conference_makes_a_person_busy_but_invited_does_not(
    conference, alice, bob, carol
):
    assert not is_busy(bob, at(10, 15), at(10, 30))
    respond(conference, bob, True)
    assert is_busy(bob, at(10, 15), at(10, 30))
    assert is_busy(alice, at(10, 15), at(10, 30))  # the host
    assert not is_busy(bob, at(11), at(12))  # ends exactly when it ends
    assert not is_busy(carol, at(10, 15), at(10, 30))


def test_declining_frees_the_time_again(conference, bob):
    respond(conference, bob, True)
    respond(conference, bob, False)
    assert not is_busy(bob, at(10, 15), at(10, 30))


def test_a_slot_cannot_be_booked_over_a_conference(conference, alice, bob, carol):
    respond(conference, bob, True)
    [slot] = open_slots(carol, DAY, time(10, 30), time(11), 30)
    with pytest.raises(SlotError):
        book(slot, bob, "Chat")
    [mine] = open_slots(alice, DAY, time(10, 30), time(11), 30)
    with pytest.raises(SlotError, match="no longer free"):
        book(mine, carol, "Chat")


def test_clash_warning_lists_busy_people(alice, bob, carol):
    [slot] = open_slots(bob, DAY, time(10), time(10, 30), 30)
    book(slot, carol, "Chat")

    assert conference_clashes([bob, carol, alice], at(10), at(11)) == [bob, carol]
    # Creating over a clash is still allowed.
    assert create_conference(alice, "Sync", at(10), at(11), [bob])


def test_a_conference_does_not_clash_with_itself(conference, bob):
    respond(conference, bob, True)
    assert conference_clashes([bob], at(10), at(11), conference=conference) == []
    assert conference_clashes([bob], at(10), at(11)) == [bob]


def test_cancelling_tells_everyone_who_has_not_declined(conference, alice, bob, carol):
    respond(conference, carol, False)
    cancel_conference(conference, alice)

    conference.refresh_from_db()
    assert conference.is_cancelled
    assert any("cancelled Quarterly review" in m.body for m in notices(bob))
    assert not any("cancelled Quarterly review" in m.body for m in notices(carol))


def test_cancelled_conference_frees_time_and_cannot_be_answered(conference, alice, bob):
    respond(conference, bob, True)
    cancel_conference(conference, alice)
    assert not is_busy(bob, at(10), at(11))
    with pytest.raises(SlotError):
        respond(conference, bob, True)


def test_only_the_host_can_cancel_or_edit(conference, bob, carol):
    with pytest.raises(PermissionDenied):
        cancel_conference(conference, bob)
    with pytest.raises(PermissionDenied):
        add_invitees(conference, bob, [carol])
    with pytest.raises(PermissionDenied):
        remove_invitee(conference, bob, carol)


def test_hosts_can_add_and_remove_invitees(conference, alice, bob, django_user_model):
    dan = django_user_model.objects.create_user(username="dan", password="pw")
    assert len(add_invitees(conference, alice, [dan, bob])) == 1  # bob already in
    assert conference.invitations.count() == 3

    assert remove_invitee(conference, alice, dan)
    assert not remove_invitee(conference, alice, dan)
    assert any("removed you from" in m.body for m in notices(dan))
