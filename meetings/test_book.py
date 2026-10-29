from datetime import time, timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from chat.models import Message
from chat.services import unread_counts

from .models import Slot, SlotRequest
from .services import (
    SlotError,
    accept_request,
    block,
    cancel,
    decline_request,
    describe,
    request_slot,
    withdraw_request,
)
from .testing import book, open_slots

pytestmark = pytest.mark.django_db

PEOPLE_URL = reverse("meetings:people")
SCHEDULE_URL = reverse("meetings:schedule")
REQUESTS_URL = reverse("meetings:requests")


@pytest.fixture
def tomorrow():
    return timezone.localdate() + timedelta(days=1)


@pytest.fixture
def slot(alice, tomorrow):
    [slot] = open_slots(alice, tomorrow, time(10), time(10, 30), 30)
    return slot


def request_url(slot):
    return reverse("meetings:request", args=[slot.pk])


def day_url(day):
    return reverse("meetings:day", args=[day.year, day.month, day.day])


# Asking never books


def test_asking_books_nothing(slot, alice, bob, tomorrow):
    request_slot(slot, bob, "  Leave request  ")

    slot.refresh_from_db()
    assert not slot.is_booked
    [ask] = SlotRequest.objects.all()
    assert (ask.requester, ask.topic, ask.status) == (
        bob,
        "Leave request",
        SlotRequest.Status.PENDING,
    )
    # neither calendar is blocked while it waits
    other = open_slots(alice, tomorrow, time(10), time(10, 30), 30)[0]
    request_slot(other, bob, "Again")


def test_asking_tells_the_host_in_their_dm(slot, alice, bob):
    request_slot(slot, bob, "Leave request")

    notice = Message.objects.get()
    assert notice.is_notice
    assert notice.author == bob
    assert notice.body == f"asked for your time {describe(slot)}: Leave request"
    assert unread_counts(alice) == {notice.conversation_id: 1}


def test_describe_uses_local_time(slot, tomorrow):
    assert describe(slot) == f"{tomorrow:%a} {tomorrow.day} {tomorrow:%b}, 10:00–10:30"


@pytest.mark.parametrize("topic", ["", "   "])
def test_a_topic_is_required(slot, bob, topic):
    with pytest.raises(SlotError, match="discuss"):
        request_slot(slot, bob, topic)
    assert not SlotRequest.objects.exists()


def test_host_cannot_ask_for_their_own_slot(slot, alice):
    with pytest.raises(SlotError, match="your own"):
        request_slot(slot, alice, "Note to self")


def test_removed_slot_cannot_be_asked_for(slot, bob):
    Slot.objects.filter(pk=slot.pk).update(cancelled_at=timezone.now())
    with pytest.raises(SlotError, match="removed"):
        request_slot(slot, bob, "Leave request")


def test_started_slot_cannot_be_asked_for(alice, bob):
    started = Slot.objects.create(
        host=alice,
        starts_at=timezone.now() - timedelta(minutes=5),
        ends_at=timezone.now() + timedelta(minutes=25),
    )
    with pytest.raises(SlotError, match="already started"):
        request_slot(started, bob, "Leave request")


def test_cannot_ask_twice_for_the_same_slot(slot, bob):
    request_slot(slot, bob, "Leave request")
    with pytest.raises(SlotError, match="already asked"):
        request_slot(slot, bob, "Leave request")


def test_requester_who_is_busy_cannot_ask(alice, bob, carol, tomorrow):
    [with_alice] = open_slots(alice, tomorrow, time(10), time(10, 30), 30)
    [with_carol] = open_slots(carol, tomorrow, time(10, 15), time(10, 45), 30)
    book(with_alice, bob, "Leave request")

    with pytest.raises(SlotError, match="already have something"):
        request_slot(with_carol, bob, "Review")


def test_several_people_can_ask_for_one_slot(slot, bob, carol):
    request_slot(slot, bob, "Leave request")
    request_slot(slot, carol, "Review")
    assert slot.requests.count() == 2


# The host decides


def test_accepting_books_the_slot_and_blocks_both_calendars(slot, alice, bob, tomorrow):
    ask = request_slot(slot, bob, "Leave request")

    accept_request(ask, alice)

    slot.refresh_from_db()
    assert slot.booked_by == bob
    assert slot.topic == "Leave request"
    assert slot.booked_at is not None
    ask.refresh_from_db()
    assert ask.status == SlotRequest.Status.ACCEPTED
    assert ask.responded_at is not None
    [other] = open_slots(bob, tomorrow, time(10), time(10, 30), 30)
    with pytest.raises(SlotError, match="already have something"):
        request_slot(other, alice, "x")


def test_accepting_tells_the_requester(slot, alice, bob):
    ask = request_slot(slot, bob, "Leave request")
    accept_request(ask, alice)

    notice = Message.objects.latest("id")
    assert notice.author == alice
    assert notice.body == (f"accepted your request for {describe(slot)}: Leave request")


def test_accepting_declines_everyone_else_waiting(slot, alice, bob, carol):
    first = request_slot(slot, bob, "Leave request")
    second = request_slot(slot, carol, "Review")

    accept_request(second, alice)

    first.refresh_from_db()
    assert first.status == SlotRequest.Status.DECLINED
    assert Slot.objects.get(pk=slot.pk).booked_by == carol
    assert "went to someone else" in Message.objects.latest("id").body


def test_only_the_host_can_accept_or_decline(slot, bob, carol):
    ask = request_slot(slot, bob, "Leave request")
    for who in (bob, carol):
        with pytest.raises(PermissionDenied):
            accept_request(ask, who)
        with pytest.raises(PermissionDenied):
            decline_request(ask, who)
    assert not Slot.objects.get(pk=slot.pk).is_booked
    assert SlotRequest.objects.get().is_pending


def test_declining_leaves_the_slot_open(slot, alice, bob, carol):
    ask = request_slot(slot, bob, "Leave request")

    decline_request(ask, alice)

    ask.refresh_from_db()
    assert ask.status == SlotRequest.Status.DECLINED
    assert not Slot.objects.get(pk=slot.pk).is_booked
    request_slot(slot, carol, "Review")  # still open for others


def test_a_request_is_answered_only_once(slot, alice, bob):
    ask = request_slot(slot, bob, "Leave request")
    decline_request(ask, alice)
    with pytest.raises(SlotError, match="already been answered"):
        accept_request(ask, alice)
    assert not Slot.objects.get(pk=slot.pk).is_booked


def test_accepting_fails_if_the_host_became_busy(alice, bob, carol, tomorrow):
    [alices] = open_slots(alice, tomorrow, time(10), time(10, 30), 30)
    [carols] = open_slots(carol, tomorrow, time(10), time(10, 30), 30)
    ask = request_slot(alices, bob, "Leave request")
    book(carols, alice, "Alice meets Carol")

    with pytest.raises(SlotError, match="no longer free"):
        accept_request(ask, alice)

    assert not Slot.objects.get(pk=alices.pk).is_booked
    assert SlotRequest.objects.get(pk=ask.pk).is_pending


def test_accepting_fails_if_the_requester_became_busy(alice, bob, carol, tomorrow):
    [alices] = open_slots(alice, tomorrow, time(10), time(10, 30), 30)
    [carols] = open_slots(carol, tomorrow, time(10), time(10, 30), 30)
    ask = request_slot(alices, bob, "Leave request")
    book(carols, bob, "Review")

    with pytest.raises(SlotError, match="already have something"):
        accept_request(ask, alice)
    assert not Slot.objects.get(pk=alices.pk).is_booked


def test_the_requester_can_withdraw(slot, alice, bob):
    ask = request_slot(slot, bob, "Leave request")
    with pytest.raises(PermissionDenied):
        withdraw_request(ask, alice)

    withdraw_request(ask, bob)

    ask.refresh_from_db()
    assert ask.status == SlotRequest.Status.WITHDRAWN
    with pytest.raises(SlotError, match="already been answered"):
        accept_request(ask, alice)


def test_blocking_declines_waiting_requests(slot, alice, bob):
    ask = request_slot(slot, bob, "Leave request")

    block(alice, [slot.pk], "Away")

    ask.refresh_from_db()
    assert ask.status == SlotRequest.Status.DECLINED


def test_host_removing_the_slot_declines_waiting_requests(slot, alice, bob):
    ask = request_slot(slot, bob, "Leave request")

    cancel(slot, alice)

    ask.refresh_from_db()
    assert ask.status == SlotRequest.Status.DECLINED


def test_booker_cancelling_frees_the_slot_for_new_requests(slot, alice, bob, carol):
    book(slot, bob, "Leave request")
    cancel(slot, bob)

    assert SlotRequest.objects.get().status == SlotRequest.Status.WITHDRAWN
    request_slot(slot, carol, "Review")


# Views


def test_people_page_says_who_has_free_upcoming_slots(client, alice, bob, tomorrow):
    slots = open_slots(alice, tomorrow, time(10), time(11, 30), 30)
    book(slots[0], bob, "Leave request")
    Slot.objects.filter(pk=slots[1].pk).update(cancelled_at=timezone.now())
    client.force_login(bob)

    response = client.get(PEOPLE_URL)

    people = {p.first_name: p.available for p in response.context["people"]}
    assert people == {"alice": True}
    assert "Available" in response.content.decode()


def test_person_page_lists_only_their_free_slots(client, alice, bob, tomorrow):
    slots = open_slots(alice, tomorrow, time(10), time(11), 30)
    book(slots[0], bob, "Leave request")
    client.force_login(bob)

    response = client.get(reverse("meetings:person_slots", args=[alice.pk]))

    assert response.context["slots"] == [slots[1]]
    assert request_url(slots[1]) in response.content.decode()


def test_person_page_marks_slots_already_asked_for(client, slot, alice, bob):
    request_slot(slot, bob, "Leave request")
    client.force_login(bob)

    response = client.get(reverse("meetings:person_slots", args=[alice.pk]))

    assert request_url(slot) not in response.content.decode()
    assert "Asked" in response.content.decode()


def test_own_person_page_goes_to_the_schedule(client, alice):
    client.force_login(alice)
    response = client.get(reverse("meetings:person_slots", args=[alice.pk]))
    assert response.url == SCHEDULE_URL  # their own calendar


def test_request_page_asks_and_books_nothing(client, slot, bob):
    client.force_login(bob)

    response = client.post(request_url(slot), {"topic": "Leave request"})

    assert response.status_code == 302
    assert response.url == REQUESTS_URL
    assert not Slot.objects.get(pk=slot.pk).is_booked
    assert SlotRequest.objects.get().requester == bob


def test_request_page_shows_rule_errors(client, slot, alice):
    client.force_login(alice)

    response = client.post(request_url(slot), {"topic": "Note to self"})

    assert response.status_code == 200
    assert "your own" in response.content.decode()


def test_request_page_requires_a_topic(client, slot, bob):
    client.force_login(bob)
    response = client.post(request_url(slot), {"topic": ""})
    assert response.context["form"].errors["topic"]
    assert not SlotRequest.objects.exists()


def test_booked_slot_is_gone(client, slot, bob, carol):
    book(slot, bob, "Leave request")
    client.force_login(carol)
    assert client.get(request_url(slot)).status_code == 404


def test_requests_page_shows_both_sides_and_the_count(client, slot, alice, bob):
    request_slot(slot, bob, "Leave request")

    client.force_login(alice)
    page = client.get(REQUESTS_URL)
    assert list(page.context["incoming"]) == list(SlotRequest.objects.all())
    assert "Leave request" in page.content.decode()
    assert page.context["waiting_time_requests"]() == 1

    client.force_login(bob)
    page = client.get(REQUESTS_URL)
    assert list(page.context["outgoing"]) == list(SlotRequest.objects.all())
    assert not page.context["incoming"]


def test_host_accepts_through_the_page(client, slot, alice, bob):
    ask = request_slot(slot, bob, "Leave request")
    client.force_login(alice)

    response = client.post(reverse("meetings:accept", args=[ask.pk]))

    assert response.url == REQUESTS_URL
    assert Slot.objects.get(pk=slot.pk).booked_by == bob


def test_others_cannot_accept_through_the_page(client, slot, bob, carol):
    ask = request_slot(slot, bob, "Leave request")
    for who in (bob, carol):
        client.force_login(who)
        response = client.post(reverse("meetings:accept", args=[ask.pk]))
        assert response.status_code == 403
    assert not Slot.objects.get(pk=slot.pk).is_booked


def test_accept_needs_post(client, slot, alice, bob):
    ask = request_slot(slot, bob, "Leave request")
    client.force_login(alice)
    assert client.get(reverse("meetings:accept", args=[ask.pk])).status_code == 405


def test_decline_and_withdraw_through_the_pages(client, slot, alice, bob, carol):
    first = request_slot(slot, bob, "Leave request")
    second = request_slot(slot, carol, "Review")

    client.force_login(alice)
    client.post(reverse("meetings:decline", args=[first.pk]))
    client.force_login(carol)
    client.post(reverse("meetings:withdraw", args=[second.pk]))

    statuses = [r.status for r in SlotRequest.objects.order_by("pk")]
    assert statuses == [SlotRequest.Status.DECLINED, SlotRequest.Status.WITHDRAWN]


def test_acceptance_is_recorded_in_history_with_who(client, slot, alice, bob):
    ask = request_slot(slot, bob, "Leave request")
    client.force_login(alice)
    client.post(reverse("meetings:accept", args=[ask.pk]))
    assert Slot.objects.get(pk=slot.pk).history.first().history_user == alice


def test_pages_require_login(client, slot, alice):
    assert client.get(PEOPLE_URL).status_code == 302
    assert client.get(REQUESTS_URL).status_code == 302
    url = reverse("meetings:person_slots", args=[alice.pk])
    assert client.get(url).status_code == 302
    assert client.post(request_url(slot), {"topic": "x"}).status_code == 302
    assert not SlotRequest.objects.exists()
