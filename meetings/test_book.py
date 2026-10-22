from datetime import time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from chat.models import Message
from chat.services import unread_counts

from .models import Slot
from .services import SlotError, book, describe, open_slots

pytestmark = pytest.mark.django_db

PEOPLE_URL = reverse("meetings:people")
SCHEDULE_URL = reverse("meetings:schedule")


@pytest.fixture
def tomorrow():
    return timezone.localdate() + timedelta(days=1)


@pytest.fixture
def slot(alice, tomorrow):
    [slot] = open_slots(alice, tomorrow, time(10), time(10, 30), 30)
    return slot


def book_url(slot):
    return reverse("meetings:book", args=[slot.pk])


# Service


def test_booking_a_free_slot(slot, bob):
    book(slot, bob, "  Leave request  ")

    slot.refresh_from_db()
    assert slot.booked_by == bob
    assert slot.topic == "Leave request"
    assert slot.booked_at is not None


def test_booking_tells_the_host_in_their_dm(slot, alice, bob):
    book(slot, bob, "Leave request")

    notice = Message.objects.get()
    assert notice.is_notice
    assert notice.author == bob
    assert notice.body == f"booked your slot {describe(slot)}: Leave request"
    assert set(notice.conversation.memberships.values_list("user", flat=True)) == {
        alice.pk,
        bob.pk,
    }
    assert unread_counts(alice) == {notice.conversation_id: 1}


def test_describe_uses_local_time(slot, tomorrow):
    assert describe(slot) == f"{tomorrow:%a} {tomorrow.day} {tomorrow:%b}, 10:00–10:30"


def test_first_come_first_served(slot, bob, carol):
    stale = Slot.objects.get(pk=slot.pk)
    book(slot, bob, "Leave request")

    with pytest.raises(SlotError, match="someone just booked"):
        book(stale, carol, "Review")

    slot.refresh_from_db()
    assert slot.booked_by == bob
    assert Message.objects.count() == 1


@pytest.mark.parametrize("topic", ["", "   "])
def test_a_topic_is_required(slot, bob, topic):
    with pytest.raises(SlotError, match="about"):
        book(slot, bob, topic)
    assert not Slot.objects.get(pk=slot.pk).is_booked


def test_host_cannot_book_their_own_slot(slot, alice):
    with pytest.raises(SlotError, match="your own"):
        book(slot, alice, "Note to self")


def test_removed_slot_cannot_be_booked(slot, bob):
    Slot.objects.filter(pk=slot.pk).update(cancelled_at=timezone.now())
    with pytest.raises(SlotError, match="removed"):
        book(slot, bob, "Leave request")


def test_started_slot_cannot_be_booked(alice, bob):
    started = Slot.objects.create(
        host=alice,
        starts_at=timezone.now() - timedelta(minutes=5),
        ends_at=timezone.now() + timedelta(minutes=25),
    )
    with pytest.raises(SlotError, match="already started"):
        book(started, bob, "Leave request")


def test_cannot_book_two_meetings_at_the_same_time(alice, bob, carol, tomorrow):
    [with_alice] = open_slots(alice, tomorrow, time(10), time(10, 30), 30)
    [with_carol] = open_slots(carol, tomorrow, time(10, 15), time(10, 45), 30)
    book(with_alice, bob, "Leave request")

    with pytest.raises(SlotError, match="already have a meeting"):
        book(with_carol, bob, "Review")


def test_cannot_book_a_host_who_is_busy_elsewhere(alice, bob, carol, tomorrow):
    [alices] = open_slots(alice, tomorrow, time(10), time(10, 30), 30)
    [carols] = open_slots(carol, tomorrow, time(10), time(10, 30), 30)
    book(carols, alice, "Alice meets Carol")

    with pytest.raises(SlotError, match="alice is no longer free"):
        book(alices, bob, "Leave request")


def test_no_limit_on_bookings_with_the_same_host(alice, bob, tomorrow):
    slots = open_slots(alice, tomorrow, time(10), time(11), 30)
    for slot in slots:
        book(slot, bob, "Leave request")
    assert bob.booked_slots.count() == 2


# Views


def test_people_page_counts_free_upcoming_slots(client, alice, bob, tomorrow):
    slots = open_slots(alice, tomorrow, time(10), time(11, 30), 30)
    book(slots[0], bob, "Leave request")
    Slot.objects.filter(pk=slots[1].pk).update(cancelled_at=timezone.now())
    client.force_login(bob)

    response = client.get(PEOPLE_URL)

    people = {p.first_name: p.free_slots for p in response.context["people"]}
    assert people == {"alice": 1}
    assert "1 free slot" in response.content.decode()


def test_person_page_lists_only_their_free_slots(client, alice, bob, tomorrow):
    slots = open_slots(alice, tomorrow, time(10), time(11), 30)
    book(slots[0], bob, "Leave request")
    client.force_login(bob)

    response = client.get(reverse("meetings:person_slots", args=[alice.pk]))

    assert response.context["slots"] == [slots[1]]
    assert book_url(slots[1]) in response.content.decode()


def test_own_person_page_goes_to_the_schedule(client, alice):
    client.force_login(alice)
    response = client.get(reverse("meetings:person_slots", args=[alice.pk]))
    assert response.url == SCHEDULE_URL


def test_book_page_books_and_goes_to_the_schedule(client, slot, bob):
    client.force_login(bob)

    response = client.post(book_url(slot), {"topic": "Leave request"})

    assert response.status_code == 302
    assert response.url == SCHEDULE_URL
    assert Slot.objects.get(pk=slot.pk).booked_by == bob
    assert "Leave request" in client.get(SCHEDULE_URL).content.decode()


def test_book_page_shows_rule_errors(client, slot, alice):
    client.force_login(alice)

    response = client.post(book_url(slot), {"topic": "Note to self"})

    assert response.status_code == 200
    assert "your own" in response.content.decode()


def test_book_page_requires_a_topic(client, slot, bob):
    client.force_login(bob)
    response = client.post(book_url(slot), {"topic": ""})
    assert response.context["form"].errors["topic"]
    assert not Slot.objects.get(pk=slot.pk).is_booked


def test_booked_slot_is_gone(client, slot, bob, carol):
    book(slot, bob, "Leave request")
    client.force_login(carol)
    assert client.get(book_url(slot)).status_code == 404


def test_booking_is_recorded_in_history_with_who(client, slot, bob):
    client.force_login(bob)
    client.post(book_url(slot), {"topic": "Leave request"})
    assert Slot.objects.get(pk=slot.pk).history.first().history_user == bob


def test_booking_pages_require_login(client, slot, alice):
    assert client.get(PEOPLE_URL).status_code == 302
    url = reverse("meetings:person_slots", args=[alice.pk])
    assert client.get(url).status_code == 302
    assert client.post(book_url(slot), {"topic": "x"}).status_code == 302
    assert not Slot.objects.get(pk=slot.pk).is_booked
