from datetime import date, datetime, time

import pytest
from django.urls import reverse
from django.utils import timezone

from .models import Slot
from .services import SlotError, block, book, cancel, open_office_hours, unblock
from .testing import open_slots

pytestmark = pytest.mark.django_db

MONDAY = date(2030, 1, 7)
BLOCK_URL = reverse("meetings:block_day", args=[2030, 1, 7])


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def pks(slots):
    return [s.pk for s in slots]


@pytest.fixture
def hours(alice):
    """Alice's 30 office-hours slots on MONDAY."""
    return open_office_hours(alice, MONDAY)


def free(host):
    return Slot.objects.filter(host=host, cancelled_at__isnull=True)


# Service


def test_blocked_slots_cannot_be_booked(alice, hours):
    assert block(alice, pks(hours[:4]), "Away") == 4
    assert free(alice).count() == 26
    assert all(s.is_cancelled for s in Slot.objects.filter(pk__in=pks(hours[:4])))


def test_only_your_own_free_future_office_hours_are_blocked(alice, bob, hours):
    bobs = open_office_hours(bob, MONDAY)
    book(hours[0], bob, "Leave request")

    assert block(alice, [hours[0].pk] + pks(bobs[:1]), "Away") == 0

    assert hours[0] in free(alice)  # booked
    assert free(bob).count() == 30


def test_block_ignores_past_slots(alice, hours, monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: at(MONDAY, 12))
    assert block(alice, pks(hours), "Away") == 21  # 12:15–13:30 and 14:00–18:00
    assert free(alice).count() == 9  # 10:00 to 12:00, already started


def test_unblock_opens_the_slots_again(alice, hours):
    block(alice, pks(hours[:3]), "Away")

    assert unblock(alice, pks(hours[:3])) == 3

    assert free(alice).count() == 30


def test_unblock_does_not_bring_back_a_cancelled_meeting(alice, bob, hours):
    book(hours[0], bob, "Leave request")
    cancel(hours[0], alice)  # the host cancels: the slot is now blocked

    assert unblock(alice, [hours[0].pk]) == 1

    slot = Slot.objects.get(pk=hours[0].pk)
    assert not slot.is_cancelled and not slot.is_booked and slot.topic == ""


def test_unblock_keeps_times_you_are_meeting_someone_blocked(alice, bob, hours):
    block(alice, [hours[0].pk], "Away")
    [bobs_10am] = open_office_hours(bob, MONDAY)[:1]
    book(bobs_10am, alice, "Review")

    assert unblock(alice, [hours[0].pk]) == 0
    assert Slot.objects.get(pk=hours[0].pk).is_cancelled


def test_blocking_is_recorded_in_history_with_who(client, alice, hours):
    client.force_login(alice)
    client.post(
        BLOCK_URL,
        {"action": "block", "slot": [hours[0].pk], f"reason_{hours[0].pk}": "Dentist"},
    )
    assert Slot.objects.get(pk=hours[0].pk).history.first().history_user == alice


# Page


def test_page_lists_office_hours_before_and_after_lunch(client, alice, bob, hours):
    book(hours[1], bob, "Leave request")
    block(alice, [hours[2].pk], "Away")
    client.force_login(alice)

    response = client.get(BLOCK_URL)

    panels = response.context["panels"]
    assert [p["title"] for p in panels] == ["Before lunch", "After lunch"]
    assert [len(p["slots"]) for p in panels] == [14, 16]
    assert [s.state for s in panels[0]["slots"][:3]] == ["free", "booked", "blocked"]
    html = response.content.decode()
    assert "10:00–13:30" in html and "14:00–18:00" in html
    assert "bob: Leave request" in html


def test_page_shows_when_you_are_meeting_someone_else(client, alice, bob, hours):
    book(open_office_hours(bob, MONDAY)[0], alice, "Review")
    client.force_login(alice)

    html = client.get(BLOCK_URL).content.decode()

    assert "You're meeting bob" in html


def test_page_opens_on_today(client, alice):
    client.force_login(alice)
    response = client.get(reverse("meetings:block_time"))
    assert response.context["day"] == timezone.localdate()


def test_sunday_says_it_is_not_an_office_day(client, alice):
    client.force_login(alice)
    sunday = reverse("meetings:block_day", args=[2030, 1, 13])
    html = client.get(sunday).content.decode()
    assert "Sunday is not an office day." in html


def test_days_not_open_yet_say_so(client, alice):
    client.force_login(alice)
    html = client.get(BLOCK_URL).content.decode()
    assert "open the office day before" in html


def test_impossible_day_is_404(client, alice):
    client.force_login(alice)
    response = client.get(reverse("meetings:block_day", args=[2030, 2, 30]))
    assert response.status_code == 404


def test_block_button_blocks_selected_slots(client, alice, hours):
    client.force_login(alice)

    response = client.post(
        BLOCK_URL,
        {
            "action": "block",
            "slot": pks(hours[:2]),
            f"reason_{hours[0].pk}": "  Dentist  ",
        },
        follow=True,
    )

    assert response.redirect_chain == [(BLOCK_URL, 302)]
    assert free(alice).count() == 28
    assert "Blocked 2 slots." in response.content.decode()
    assert {s.block_reason for s in Slot.objects.filter(pk__in=pks(hours[:2]))} == {
        "Dentist"
    }
    assert "Blocked: Dentist" in client.get(BLOCK_URL).content.decode()


def test_separate_stretches_each_need_their_own_reason(client, alice, hours):
    client.force_login(alice)
    picked = [hours[0], hours[1], hours[3]]  # 10:00–11:00 and 11:30–12:00
    data = {"action": "block", "slot": pks(picked), f"reason_{hours[0].pk}": "Dentist"}

    response = client.post(BLOCK_URL, data, follow=True)

    assert "blocking each stretch" in response.content.decode()
    assert free(alice).count() == 30  # nothing was blocked

    data[f"reason_{hours[3].pk}"] = "Call"
    client.post(BLOCK_URL, data)
    reasons = {s.pk: s.block_reason for s in Slot.objects.filter(pk__in=pks(picked))}
    assert reasons == {
        hours[0].pk: "Dentist",
        hours[1].pk: "Dentist",
        hours[3].pk: "Call",
    }


def test_blocking_needs_a_reason(client, alice, hours):
    client.force_login(alice)

    client.post(BLOCK_URL, {"action": "block", "slot": [hours[0].pk]})
    client.post(
        BLOCK_URL,
        {"action": "block", "slot": [hours[0].pk], f"reason_{hours[0].pk}": "  "},
    )
    client.post(BLOCK_URL, {"action": "block_day"})

    assert free(alice).count() == 30
    with pytest.raises(SlotError):
        block(alice, [hours[0].pk], " ")


def test_unblocking_clears_the_reason(alice, hours):
    block(alice, [hours[0].pk], "Dentist")
    unblock(alice, [hours[0].pk])

    assert Slot.objects.get(pk=hours[0].pk).block_reason == ""


def test_block_whole_day_leaves_meetings_alone(client, alice, bob, hours):
    book(hours[5], bob, "Leave request")
    client.force_login(alice)

    response = client.post(
        BLOCK_URL, {"action": "block_day", "reason_day": "Offsite"}, follow=True
    )

    assert list(free(alice)) == [Slot.objects.get(pk=hours[5].pk)]
    assert "Blocked 29 slots." in response.content.decode()


def test_unblock_button_reports_slots_that_stayed_blocked(client, alice, bob, hours):
    block(alice, pks(hours[:2]), "Away")
    book(open_office_hours(bob, MONDAY)[0], alice, "Review")  # 10:00
    client.force_login(alice)

    response = client.post(
        BLOCK_URL, {"action": "unblock", "slot": pks(hours[:2])}, follow=True
    )

    html = response.content.decode()
    assert "Unblocked 1 slot." in html
    assert "1 slot stayed blocked" in html


def test_people_cannot_block_someone_elses_time(client, alice, bob, hours):
    client.force_login(bob)
    client.post(BLOCK_URL, {"action": "block_day"})
    client.post(BLOCK_URL, {"action": "block", "slot": pks(hours)})
    assert free(alice).count() == 30


def test_block_page_requires_login(client):
    assert client.get(reverse("meetings:block_time")).status_code == 302


def test_meetings_menu_links_to_block_time(client, alice):
    client.force_login(alice)
    html = client.get(reverse("meetings:schedule")).content.decode()
    assert reverse("meetings:block_time") in html


def test_slots_opened_by_hand_are_listed_and_can_be_blocked(client, alice):
    # Opened before office hours existed: they fill the day, so office hours
    # only add the one time that was free.
    by_hand = open_slots(alice, MONDAY, time(10), time(18), 15)
    by_hand[12].cancelled_at = timezone.now()  # 13:00, removed
    by_hand[12].save()
    open_office_hours(alice, MONDAY)
    client.force_login(alice)

    panels = client.get(BLOCK_URL).context["panels"]

    shown = [s for panel in panels for s in panel["slots"]]
    assert len(shown) == 32  # 10:00–18:00, with the 13:00 office-hours slot
    assert by_hand[12] not in shown  # the removed one isn't shown twice
    assert block(alice, [by_hand[0].pk], "Away") == 1
