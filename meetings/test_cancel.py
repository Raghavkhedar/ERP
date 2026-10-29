from datetime import time, timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from chat.models import Message
from chat.services import unread_counts

from .models import Slot
from .services import SlotError, cancel, describe
from .testing import book, open_slots

pytestmark = pytest.mark.django_db


@pytest.fixture
def slot(alice):
    tomorrow = timezone.localdate() + timedelta(days=1)
    [slot] = open_slots(alice, tomorrow, time(10), time(10, 30), 30)
    return slot


@pytest.fixture
def booked(slot, bob):
    return book(slot, bob, "Leave request")


def cancel_url(slot):
    return reverse("meetings:cancel", args=[slot.pk])


def day_url(slot):
    day = timezone.localdate(slot.starts_at)
    return reverse("meetings:day", args=[day.year, day.month, day.day])


def latest_notice():
    return Message.objects.order_by("-id").first()


# Service


def test_booker_cancelling_frees_the_slot(booked, bob):
    cancel(booked, bob)

    booked.refresh_from_db()
    assert not booked.is_booked
    assert not booked.is_cancelled
    assert booked.topic == ""
    assert booked.booked_at is None


def test_booker_cancelling_tells_the_host(booked, alice, bob):
    cancel(booked, bob)

    notice = latest_notice()
    assert notice.is_notice
    assert notice.author == bob
    assert notice.body == (
        f"cancelled their booking for {describe(booked)} (Leave request)"
    )
    assert unread_counts(alice) == {notice.conversation_id: 2}


def test_freed_slot_can_be_booked_again(booked, bob, carol):
    cancel(booked, bob)
    book(booked, carol, "Review")
    assert Slot.objects.get(pk=booked.pk).booked_by == carol


def test_host_cancelling_removes_the_slot_and_tells_the_booker(booked, alice, bob):
    cancel(booked, alice)

    booked.refresh_from_db()
    assert booked.is_cancelled
    assert booked.booked_by == bob
    notice = latest_notice()
    assert notice.author == alice
    assert notice.body == (
        f"cancelled your booking for {describe(booked)} (Leave request)"
    )
    assert notice.conversation_id in unread_counts(bob)


def test_host_removing_a_free_slot_tells_nobody(slot, alice):
    cancel(slot, alice)
    assert Slot.objects.get(pk=slot.pk).is_cancelled
    assert not Message.objects.exists()


def test_removed_slot_cannot_be_booked(slot, alice, bob):
    cancel(slot, alice)
    with pytest.raises(SlotError, match="removed"):
        book(slot, bob, "Leave request")


def test_others_cannot_cancel(booked, carol):
    with pytest.raises(PermissionDenied):
        cancel(booked, carol)
    assert Slot.objects.get(pk=booked.pk).booked_by_id is not None


def test_cancelling_twice_is_refused(slot, alice):
    cancel(slot, alice)
    with pytest.raises(SlotError, match="already been removed"):
        cancel(slot, alice)


def test_finished_meetings_cannot_be_cancelled(alice, bob):
    past = Slot.objects.create(
        host=alice,
        starts_at=timezone.now() - timedelta(hours=2),
        ends_at=timezone.now() - timedelta(hours=1),
        booked_by=bob,
        topic="Leave request",
        booked_at=timezone.now() - timedelta(days=1),
    )
    with pytest.raises(SlotError, match="already over"):
        cancel(past, bob)


# Views


def test_booker_cancels_from_the_day(client, booked, bob):
    client.force_login(bob)
    assert cancel_url(booked) in client.get(day_url(booked)).content.decode()

    response = client.post(cancel_url(booked), follow=True)

    assert response.redirect_chain == [(day_url(booked), 302)]
    assert "Cancelled" in response.content.decode()
    assert not Slot.objects.get(pk=booked.pk).is_booked


def test_host_cancels_from_the_day(client, booked, alice):
    client.force_login(alice)
    response = client.post(cancel_url(booked), follow=True)
    assert "Cancelled and the slot removed" in response.content.decode()
    assert Slot.objects.get(pk=booked.pk).is_cancelled


def test_host_removes_a_free_slot_from_the_day(client, slot, alice):
    client.force_login(alice)
    response = client.post(cancel_url(slot), follow=True)
    assert "Slot removed" in response.content.decode()
    assert response.context["slots"] == []


def test_rule_errors_are_shown_on_the_day(client, slot, alice):
    client.force_login(alice)
    client.post(cancel_url(slot))
    response = client.post(cancel_url(slot), follow=True)
    assert "already been removed" in response.content.decode()


def test_others_get_403(client, booked, carol):
    client.force_login(carol)
    assert client.post(cancel_url(booked)).status_code == 403


def test_cancelling_is_recorded_in_history_with_who(client, booked, bob):
    client.force_login(bob)
    client.post(cancel_url(booked))
    assert Slot.objects.get(pk=booked.pk).history.first().history_user == bob


def test_cancelling_requires_post_and_login(client, booked, bob):
    assert client.post(cancel_url(booked)).status_code == 302
    client.force_login(bob)
    assert client.get(cancel_url(booked)).status_code == 405
    assert Slot.objects.get(pk=booked.pk).is_booked
