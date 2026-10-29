from datetime import datetime, time, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from chat.models import Message

from .models import Slot
from .services import block, cancel, send_reminders
from .testing import book, open_slots

pytestmark = pytest.mark.django_db

DAY = timezone.localdate() + timedelta(days=1)


def at(hour, minute=0):
    return timezone.make_aware(datetime.combine(DAY, time(hour, minute)))


@pytest.fixture
def meeting(alice, bob):
    [slot] = open_slots(alice, DAY, time(10), time(10, 30), 30)
    return book(slot, bob, "Leave request")


def reminders():
    return Message.objects.filter(body__startswith="Reminder:")


def test_both_people_are_reminded_ten_minutes_before(meeting, alice, bob):
    assert send_reminders(now=at(9, 50)) == 1

    to_alice, to_bob = reminders().order_by("id")
    assert to_alice.author == bob and "time with bob at 10:00–10:30" in to_alice.body
    assert to_bob.author == alice and "time with alice at 10:00–10:30" in to_bob.body
    assert "Leave request" in to_bob.body
    meeting.refresh_from_db()
    assert meeting.reminded_at == at(9, 50)


def test_too_early_is_not_reminded_yet(meeting):
    assert send_reminders(now=at(9, 49)) == 0
    assert not reminders().exists()


def test_each_meeting_is_reminded_once(meeting):
    send_reminders(now=at(9, 50))
    assert send_reminders(now=at(9, 55)) == 0
    assert reminders().count() == 2


def test_started_meetings_are_not_reminded(meeting):
    assert send_reminders(now=at(10, 1)) == 0


def test_unbooked_and_cancelled_slots_are_not_reminded(alice, bob, meeting):
    open_slots(alice, DAY, time(11), time(11, 30), 30)  # free
    [gone] = open_slots(alice, DAY, time(10, 30), time(11), 30)
    book(gone, bob, "Other")
    block(alice, [gone.pk], "Away")  # no-op: booked, so stays booked
    cancel(meeting, bob)

    assert send_reminders(now=at(10, 25)) == 1  # only the 10:30 one


def test_a_rebooked_slot_is_reminded_again(meeting, alice, bob, carol):
    send_reminders(now=at(9, 50))
    cancel(meeting, bob)
    book(Slot.objects.get(pk=meeting.pk), carol, "Review")

    assert send_reminders(now=at(9, 55)) == 1


def test_reminders_do_not_add_history_rows(meeting):
    before = meeting.history.count()
    send_reminders(now=at(9, 50))
    assert meeting.history.count() == before


def test_the_command_runs(meeting, capsys, monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: at(9, 55))
    call_command("send_meeting_reminders")
    assert "1 meeting" in capsys.readouterr().out
