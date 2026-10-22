from datetime import date, datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .models import Slot

pytestmark = pytest.mark.django_db

SCHEDULE_URL = reverse("meetings:schedule")


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def make_slot(host, day, hour, minute=0, minutes=30, booked_by=None, topic=""):
    starts = at(day, hour, minute)
    return Slot.objects.create(
        host=host,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=minutes),
        booked_by=booked_by,
        topic=topic or ("Catch-up" if booked_by else ""),
        booked_at=timezone.now() if booked_by else None,
    )


def day_url(day):
    return reverse("meetings:day", args=[day.year, day.month, day.day])


def month_url(day):
    return reverse("meetings:month", args=[day.year, day.month])


def cell(response, day):
    return next(
        c for week in response.context["weeks"] for c in week if c["date"] == day
    )


@pytest.fixture
def tomorrow():
    return timezone.localdate() + timedelta(days=1)


# Month


def test_calendar_opens_on_this_month(client, alice):
    client.force_login(alice)

    response = client.get(SCHEDULE_URL)

    today = timezone.localdate()
    assert response.context["month"] == today.replace(day=1)
    assert cell(response, today)["is_today"]
    assert today.strftime("%B %Y") in response.content.decode()


def test_month_grid_starts_on_monday_and_covers_whole_weeks(client, alice):
    client.force_login(alice)

    weeks = client.get(reverse("meetings:month", args=[2026, 10])).context["weeks"]

    assert weeks[0][0]["date"] == date(2026, 9, 28)  # a Monday
    assert weeks[-1][-1]["date"] == date(2026, 11, 1)  # a Sunday
    assert not weeks[0][0]["in_month"]
    assert all(len(week) == 7 for week in weeks)


def test_month_shows_meetings_both_ways_and_counts_free_slots(
    client, alice, bob, carol, tomorrow
):
    hosted = make_slot(alice, tomorrow, 10, booked_by=bob, topic="Leave request")
    guest = make_slot(carol, tomorrow, 11, booked_by=alice, topic="Review")
    make_slot(alice, tomorrow, 15)
    make_slot(alice, tomorrow, 16)
    make_slot(bob, tomorrow, 12)  # someone else's free slot
    client.force_login(alice)

    response = client.get(month_url(tomorrow))

    day = cell(response, tomorrow)
    assert day["meetings"] == [hosted, guest]
    assert [m.other for m in day["meetings"]] == [bob, carol]
    assert day["free"] == 2
    assert "2 free slots" in response.content.decode()


def test_month_leaves_out_cancelled_and_ended_free_slots(client, alice, bob):
    today = timezone.localdate()
    ended = timezone.now() - timedelta(hours=1)
    Slot.objects.create(
        host=alice, starts_at=ended - timedelta(minutes=30), ends_at=ended
    )
    cancelled = make_slot(alice, today + timedelta(days=1), 10, booked_by=bob)
    cancelled.cancelled_at = timezone.now()
    cancelled.save()
    client.force_login(alice)

    response = client.get(SCHEDULE_URL)

    week_cells = [c for week in response.context["weeks"] for c in week]
    assert not any(c["meetings"] or c["free"] for c in week_cells)


def test_month_keeps_past_meetings(client, alice, bob):
    past = make_slot(alice, timezone.localdate() - timedelta(days=1), 10, booked_by=bob)
    client.force_login(alice)

    response = client.get(month_url(timezone.localdate() - timedelta(days=1)))

    assert cell(response, timezone.localdate(past.starts_at))["meetings"] == [past]


def test_month_links_to_neighbours_and_days(client, alice):
    client.force_login(alice)

    html = client.get(reverse("meetings:month", args=[2026, 1])).content.decode()

    assert reverse("meetings:month", args=[2025, 12]) in html
    assert reverse("meetings:month", args=[2026, 2]) in html
    assert day_url(date(2026, 1, 15)) in html


@pytest.mark.parametrize("year, month", [(2026, 13), (2026, 0), (1999, 5)])
def test_impossible_month_is_404(client, alice, year, month):
    client.force_login(alice)
    response = client.get(reverse("meetings:month", args=[year, month]))
    assert response.status_code == 404


# Day


def test_day_lists_the_days_meetings_in_order(client, alice, bob, carol, tomorrow):
    later = make_slot(carol, tomorrow, 14, booked_by=alice, topic="Review")
    earlier = make_slot(alice, tomorrow, 10, booked_by=bob, topic="Leave request")
    make_slot(alice, tomorrow + timedelta(days=1), 10, booked_by=bob)
    client.force_login(alice)

    response = client.get(day_url(tomorrow))

    assert response.context["slots"] == [earlier, later]
    html = response.content.decode()
    assert "Booked your slot" in html
    assert "You booked their slot" in html
    assert reverse("meetings:cancel", args=[earlier.pk]) in html


def test_day_places_slots_on_the_timeline(client, alice, tomorrow):
    slot = make_slot(alice, tomorrow, 9, 30, minutes=45)
    client.force_login(alice)

    response = client.get(day_url(tomorrow))

    [shown] = response.context["slots"]
    assert shown.top == 96  # 1.5 hours below 08:00, 64px an hour
    assert shown.height == 48
    assert shown == slot


def test_day_timeline_stretches_to_early_and_late_slots(client, alice, tomorrow):
    make_slot(alice, tomorrow, 6)
    make_slot(alice, tomorrow, 21, 30)
    client.force_login(alice)

    hours = [hour for hour, _ in client.get(day_url(tomorrow)).context["hours"]]

    assert hours[0] == time(6)
    assert hours[-1] == time(21)


def test_empty_future_day_offers_to_book(client, alice, tomorrow):
    client.force_login(alice)

    html = client.get(day_url(tomorrow)).content.decode()

    assert "Nothing on this day." in html
    assert reverse("meetings:people") in html


def test_ended_meetings_have_no_cancel_button(client, alice, bob):
    yesterday = timezone.localdate() - timedelta(days=1)
    past = make_slot(alice, yesterday, 10, booked_by=bob)
    client.force_login(alice)

    html = client.get(day_url(yesterday)).content.decode()

    assert reverse("meetings:cancel", args=[past.pk]) not in html


def test_impossible_day_is_404(client, alice):
    client.force_login(alice)
    assert client.get(reverse("meetings:day", args=[2026, 2, 30])).status_code == 404
