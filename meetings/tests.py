from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse
from django.utils import timezone

from .models import Invitation, InvitationStatus, Meeting

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(username="alice", password="pw")


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(username="bob", password="pw")


def make_meeting(organizer, title="Weekly sync", minutes=30, **extra):
    starts_at = timezone.now() + timedelta(days=1)
    return Meeting.objects.create(
        organizer=organizer,
        title=title,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=minutes),
        **extra,
    )


@pytest.fixture
def meeting(alice):
    return make_meeting(alice)


def assert_rejected(create):
    with pytest.raises(IntegrityError), transaction.atomic():
        create()


# Meetings


def test_meeting_can_be_created(meeting):
    assert meeting.title == "Weekly sync"
    assert not meeting.is_cancelled
    assert "Weekly sync" in str(meeting)


@pytest.mark.parametrize("minutes", [0, -30])
def test_meeting_must_end_after_it_starts(alice, minutes):
    assert_rejected(lambda: make_meeting(alice, minutes=minutes))


@pytest.mark.parametrize("title", ["", "   "])
def test_meeting_needs_a_title(alice, title):
    assert_rejected(lambda: make_meeting(alice, title=title))


def test_cancelled_meeting_knows_it(alice):
    assert make_meeting(alice, cancelled_at=timezone.now()).is_cancelled


def test_meetings_are_ordered_by_start(alice):
    later = make_meeting(alice, title="Later")
    later.starts_at += timedelta(hours=2)
    later.ends_at += timedelta(hours=2)
    later.save()
    sooner = make_meeting(alice, title="Sooner")
    assert list(Meeting.objects.all()) == [sooner, later]


# Invitations


def test_invitation_starts_pending(meeting, bob):
    invitation = Invitation.objects.create(meeting=meeting, invitee=bob)
    assert invitation.status == InvitationStatus.PENDING
    assert invitation.responded_at is None
    assert list(meeting.invitations.all()) == [invitation]


def test_person_is_invited_only_once(meeting, bob):
    Invitation.objects.create(meeting=meeting, invitee=bob)
    assert_rejected(lambda: Invitation.objects.create(meeting=meeting, invitee=bob))


def test_unknown_status_is_rejected(meeting, bob):
    assert_rejected(
        lambda: Invitation.objects.create(meeting=meeting, invitee=bob, status="maybe")
    )


@pytest.mark.parametrize(
    "status", [InvitationStatus.ACCEPTED, InvitationStatus.DECLINED]
)
def test_answer_needs_a_response_time(meeting, bob, status):
    assert_rejected(
        lambda: Invitation.objects.create(meeting=meeting, invitee=bob, status=status)
    )
    invitation = Invitation.objects.create(
        meeting=meeting, invitee=bob, status=status, responded_at=timezone.now()
    )
    assert invitation.status == status


def test_pending_invitation_cannot_have_a_response_time(meeting, bob):
    assert_rejected(
        lambda: Invitation.objects.create(
            meeting=meeting, invitee=bob, responded_at=timezone.now()
        )
    )


def test_meeting_with_invitations_cannot_be_deleted(meeting, bob):
    Invitation.objects.create(meeting=meeting, invitee=bob)
    with pytest.raises(ProtectedError):
        meeting.delete()


# History


def test_meeting_and_invitation_changes_are_recorded(meeting, bob):
    meeting.title = "Planning"
    meeting.save()
    invitation = Invitation.objects.create(meeting=meeting, invitee=bob)
    invitation.status = InvitationStatus.ACCEPTED
    invitation.responded_at = timezone.now()
    invitation.save()

    assert meeting.history.count() == 2
    assert meeting.history.first().title == "Planning"
    assert invitation.history.count() == 2


# Admin


def test_admin_meeting_list_loads(admin_client, meeting):
    response = admin_client.get(reverse("admin:meetings_meeting_changelist"))
    assert response.status_code == 200


def test_admin_meeting_page_loads(admin_client, meeting):
    url = reverse("admin:meetings_meeting_change", args=[meeting.pk])
    assert admin_client.get(url).status_code == 200
