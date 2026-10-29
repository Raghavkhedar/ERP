from datetime import date, datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .models import Slot
from .services import (
    office_days_open,
    open_office_hours,
    open_upcoming_office_hours,
)
from .testing import book

pytestmark = pytest.mark.django_db

MONDAY = date(2030, 1, 7)
SATURDAY = date(2030, 1, 12)
SUNDAY = date(2030, 1, 13)


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def local_times(slots):
    return [timezone.localtime(s.starts_at).strftime("%H:%M") for s in slots]


@pytest.fixture
def now_is(monkeypatch):
    """Pretend the clock reads this moment."""

    def set_now(moment):
        monkeypatch.setattr(timezone, "now", lambda: moment)

    return set_now


# Service


def test_office_hours_are_15_minute_slots_with_a_lunch_break(alice):
    slots = open_office_hours(alice, MONDAY)

    times = local_times(slots)
    assert len(slots) == 30
    assert times[0] == "10:00"
    assert times[-1] == "17:45"
    assert "13:15" in times and "13:30" not in times and "13:45" not in times
    assert "14:00" in times
    assert all(s.ends_at - s.starts_at == timedelta(minutes=15) for s in slots)
    assert all(s.office_hours and s.host == alice and not s.is_booked for s in slots)


def test_saturday_is_an_office_day_and_sunday_is_not(alice):
    assert len(open_office_hours(alice, MONDAY + timedelta(days=5))) == 30
    assert open_office_hours(alice, SUNDAY) == []


def test_a_day_is_filled_only_once(alice):
    open_office_hours(alice, MONDAY)
    assert open_office_hours(alice, MONDAY) == []
    assert Slot.objects.count() == 30


def test_removed_office_hours_do_not_come_back(alice):
    open_office_hours(alice, MONDAY)
    Slot.objects.update(cancelled_at=timezone.now())

    assert open_office_hours(alice, MONDAY) == []


def test_times_already_taken_are_skipped(alice, bob):
    Slot.objects.create(host=alice, starts_at=at(MONDAY, 9), ends_at=at(MONDAY, 10, 30))
    Slot.objects.create(
        host=bob,
        starts_at=at(MONDAY, 15),
        ends_at=at(MONDAY, 15, 15),
        booked_by=alice,
        topic="Review",
        booked_at=timezone.now(),
    )

    times = local_times(open_office_hours(alice, MONDAY))

    assert times[:2] == ["10:30", "10:45"]
    assert "15:00" not in times
    assert len(times) == 27


def test_times_already_past_are_skipped(alice, now_is):
    now_is(at(MONDAY, 16, 5))

    times = local_times(open_office_hours(alice, MONDAY))

    assert times == ["16:15", "16:30", "16:45", "17:00", "17:15", "17:30", "17:45"]


def test_office_hours_can_be_booked(alice, bob):
    slot = open_office_hours(alice, MONDAY)[0]

    book(slot, bob, "Leave request")

    slot.refresh_from_db()
    assert slot.booked_by == bob


# Opening on demand


@pytest.mark.parametrize(
    "moment, days",
    [
        (at(MONDAY, 8), [MONDAY, MONDAY + timedelta(days=1)]),
        (at(MONDAY, 17, 59), [MONDAY, MONDAY + timedelta(days=1)]),
        (at(MONDAY, 18), [MONDAY + timedelta(days=1)]),  # today's are over
        (at(SATURDAY, 9), [SATURDAY, MONDAY + timedelta(days=7)]),  # skips Sunday
        (at(SUNDAY, 9), [MONDAY + timedelta(days=7)]),
    ],
)
def test_office_days_open_are_today_and_the_next_office_day(now_is, moment, days):
    now_is(moment)
    assert office_days_open() == days


def test_upcoming_office_hours_open_for_active_people(alice, bob, now_is):
    now_is(at(MONDAY, 8))
    bob.is_active = False
    bob.save()

    open_upcoming_office_hours()

    assert not Slot.objects.filter(host=bob).exists()
    days = {timezone.localdate(s.starts_at) for s in Slot.objects.all()}
    assert days == {MONDAY, MONDAY + timedelta(days=1)}
    assert Slot.objects.count() == 60


def test_opening_upcoming_office_hours_again_changes_nothing(alice, bob, now_is):
    now_is(at(MONDAY, 8))
    open_upcoming_office_hours()
    Slot.objects.filter(host=alice).first().delete()  # a gap is not refilled

    open_upcoming_office_hours()

    assert Slot.objects.count() == 119


@pytest.mark.office_hours_on_demand
def test_meetings_pages_open_office_hours(client, alice, bob, now_is):
    now_is(at(MONDAY, 8))
    client.force_login(bob)

    response = client.get(reverse("meetings:people"))

    [person] = response.context["people"]
    assert person == alice and person.available


# Day view


def test_day_shows_open_office_hours_as_blocks(client, alice, bob, now_is):
    now_is(at(MONDAY, 8))
    slots = open_office_hours(alice, MONDAY)
    book(slots[4], bob, "Leave request")  # 11:00
    client.force_login(alice)

    response = client.get(
        reverse("meetings:day", args=[MONDAY.year, MONDAY.month, MONDAY.day])
    )

    shown = [
        (local_times([s])[0], s.ends_at, getattr(s, "free", None))
        for s in response.context["slots"]
    ]
    assert shown == [
        ("10:00", at(MONDAY, 11), 4),
        ("11:00", at(MONDAY, 11, 15), None),
        ("11:15", at(MONDAY, 13, 30), 9),
        ("14:00", at(MONDAY, 18), 16),
    ]
    page = response.content.decode()
    assert "Office hours · 16 open" in page
    assert 'href="#hours-1400"' in page and 'id="hours-1400"' in page
