from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse
from django.utils import timezone

from .models import Slot

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice", first_name="alice", password="pw"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="bob", first_name="bob", password="pw"
    )


def make_slot(host, minutes=30, **extra):
    starts_at = timezone.now() + timedelta(days=1)
    return Slot.objects.create(
        host=host,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=minutes),
        **extra,
    )


def booking(user, topic="Leave request"):
    return {"booked_by": user, "topic": topic, "booked_at": timezone.now()}


@pytest.fixture
def slot(alice):
    return make_slot(alice)


def assert_rejected(create):
    with pytest.raises(IntegrityError), transaction.atomic():
        create()


# Open slots


def test_open_slot_can_be_created(slot):
    assert not slot.is_booked
    assert not slot.is_cancelled
    assert slot.topic == ""


@pytest.mark.parametrize("minutes", [0, -30])
def test_slot_must_end_after_it_starts(alice, minutes):
    assert_rejected(lambda: make_slot(alice, minutes=minutes))


def test_cancelled_slot_knows_it(alice):
    assert make_slot(alice, cancelled_at=timezone.now()).is_cancelled


def test_slots_are_ordered_by_start(alice):
    later = make_slot(alice)
    later.starts_at += timedelta(hours=2)
    later.ends_at += timedelta(hours=2)
    later.save()
    sooner = make_slot(alice)
    assert list(Slot.objects.all()) == [sooner, later]


# Bookings


def test_slot_can_be_booked(alice, bob):
    slot = make_slot(alice, **booking(bob))
    assert slot.is_booked
    assert list(bob.booked_slots.all()) == [slot]
    assert list(alice.hosted_slots.all()) == [slot]


def test_host_cannot_book_their_own_slot(alice):
    assert_rejected(lambda: make_slot(alice, **booking(alice)))


@pytest.mark.parametrize("topic", ["", "   "])
def test_booking_needs_a_topic(alice, bob, topic):
    assert_rejected(lambda: make_slot(alice, **booking(bob, topic=topic)))


def test_booking_needs_a_booking_time(alice, bob):
    assert_rejected(lambda: make_slot(alice, booked_by=bob, topic="Leave request"))


@pytest.mark.parametrize(
    "extra", [{"topic": "Leave request"}, {"booked_at": timezone.now()}]
)
def test_open_slot_has_no_booking_details(alice, extra):
    assert_rejected(lambda: make_slot(alice, **extra))


def test_host_with_slots_cannot_be_deleted(slot, alice):
    with pytest.raises(ProtectedError):
        alice.delete()


# History


def test_slot_changes_are_recorded(slot, bob):
    for field, value in booking(bob).items():
        setattr(slot, field, value)
    slot.save()

    assert slot.history.count() == 2
    assert slot.history.first().booked_by == bob


# Admin


def test_admin_slot_list_loads(admin_client, slot):
    response = admin_client.get(reverse("admin:meetings_slot_changelist"))
    assert response.status_code == 200


def test_admin_slot_page_loads(admin_client, slot):
    url = reverse("admin:meetings_slot_change", args=[slot.pk])
    assert admin_client.get(url).status_code == 200
