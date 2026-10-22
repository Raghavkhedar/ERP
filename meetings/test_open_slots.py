from datetime import time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .models import Slot
from .services import SlotError, open_slots

pytestmark = pytest.mark.django_db

OPEN_URL = reverse("meetings:open_slots")
SCHEDULE_URL = reverse("meetings:schedule")


@pytest.fixture
def tomorrow():
    return timezone.localdate() + timedelta(days=1)


def local_times(slots):
    return [
        (
            timezone.localtime(s.starts_at).strftime("%H:%M"),
            timezone.localtime(s.ends_at).strftime("%H:%M"),
        )
        for s in slots
    ]


# Service


def test_range_is_split_into_slots(alice, tomorrow):
    slots = open_slots(alice, tomorrow, time(10), time(12), 30)

    assert local_times(Slot.objects.all()) == [
        ("10:00", "10:30"),
        ("10:30", "11:00"),
        ("11:00", "11:30"),
        ("11:30", "12:00"),
    ]
    assert all(s.host == alice and not s.is_booked for s in slots)


def test_a_leftover_shorter_than_a_slot_is_dropped(alice, tomorrow):
    open_slots(alice, tomorrow, time(10), time(11, 10), 30)
    assert local_times(Slot.objects.all()) == [("10:00", "10:30"), ("10:30", "11:00")]


@pytest.mark.parametrize(
    "start, end, minutes, message",
    [
        (time(11), time(10), 30, "after the start"),
        (time(10), time(10), 30, "after the start"),
        (time(10), time(10, 20), 30, "shorter than one 30-minute slot"),
    ],
)
def test_bad_ranges_are_rejected(alice, tomorrow, start, end, minutes, message):
    with pytest.raises(SlotError, match=message):
        open_slots(alice, tomorrow, start, end, minutes)
    assert not Slot.objects.exists()


def test_slots_cannot_start_in_the_past(alice):
    yesterday = timezone.localdate() - timedelta(days=1)
    with pytest.raises(SlotError, match="past"):
        open_slots(alice, yesterday, time(10), time(11), 30)
    assert not Slot.objects.exists()


def test_overlapping_your_own_slots_is_rejected_whole(alice, tomorrow):
    open_slots(alice, tomorrow, time(10), time(11), 30)

    with pytest.raises(SlotError, match="10:00–10:30"):
        open_slots(alice, tomorrow, time(9), time(12), 30)
    assert Slot.objects.count() == 2


def test_adjacent_ranges_are_fine(alice, tomorrow):
    open_slots(alice, tomorrow, time(10), time(11), 30)
    open_slots(alice, tomorrow, time(11), time(12), 30)
    assert Slot.objects.count() == 4


def test_cancelled_slots_do_not_block(alice, tomorrow):
    open_slots(alice, tomorrow, time(10), time(11), 30)
    Slot.objects.update(cancelled_at=timezone.now())

    open_slots(alice, tomorrow, time(10), time(11), 30)

    assert Slot.objects.filter(cancelled_at__isnull=True).count() == 2


def test_other_peoples_slots_do_not_block(alice, bob, tomorrow):
    open_slots(bob, tomorrow, time(10), time(11), 30)
    open_slots(alice, tomorrow, time(10), time(11), 30)
    assert Slot.objects.count() == 4


def test_cannot_open_slots_while_booked_with_someone_else(alice, bob, tomorrow):
    [slot, _] = open_slots(bob, tomorrow, time(10), time(11), 30)
    Slot.objects.filter(pk=slot.pk).update(
        booked_by=alice, topic="Review", booked_at=timezone.now()
    )

    with pytest.raises(SlotError, match="meeting booked"):
        open_slots(alice, tomorrow, time(9), time(12), 30)


# Views


def test_form_opens_slots_and_goes_to_that_day(client, alice, tomorrow):
    client.force_login(alice)

    response = client.post(
        OPEN_URL,
        {"date": tomorrow, "start": "10:00", "end": "11:00", "minutes": "30"},
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "meetings:day", args=[tomorrow.year, tomorrow.month, tomorrow.day]
    )
    assert Slot.objects.filter(host=alice).count() == 2


def test_form_shows_rule_errors(client, alice, tomorrow):
    client.force_login(alice)

    response = client.post(
        OPEN_URL,
        {"date": tomorrow, "start": "11:00", "end": "10:00", "minutes": "30"},
    )

    assert response.status_code == 200
    assert "after the start" in response.content.decode()
    assert not Slot.objects.exists()


def test_form_rejects_odd_slot_lengths(client, alice, tomorrow):
    client.force_login(alice)
    response = client.post(
        OPEN_URL,
        {"date": tomorrow, "start": "10:00", "end": "11:00", "minutes": "7"},
    )
    assert response.context["form"].errors["minutes"]
    assert not Slot.objects.exists()


def test_opened_slots_are_recorded_in_history_with_who(client, alice, tomorrow):
    client.force_login(alice)
    client.post(
        OPEN_URL,
        {"date": tomorrow, "start": "10:00", "end": "10:30", "minutes": "30"},
    )
    assert Slot.objects.get().history.get().history_user == alice


def test_meetings_pages_require_login(client):
    assert client.get(SCHEDULE_URL).status_code == 302
    assert client.get(OPEN_URL).status_code == 302


def test_top_bar_links_to_meetings(client, alice):
    client.force_login(alice)
    assert SCHEDULE_URL in client.get(reverse("home")).content.decode()
