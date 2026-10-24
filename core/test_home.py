from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from meetings.models import Slot

pytestmark = pytest.mark.django_db


@pytest.fixture
def asha(django_user_model):
    return django_user_model.objects.create_user(
        username="S123", first_name="Asha", last_name="Rao", password="pw"
    )


@pytest.fixture
def vikram(django_user_model):
    return django_user_model.objects.create_user(
        username="S124", first_name="Vikram", last_name="Mehta", password="pw"
    )


def make_slot(host, hours_from_now, booked_by=None, topic=""):
    starts = timezone.now() + timedelta(hours=hours_from_now)
    return Slot.objects.create(
        host=host,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=30),
        booked_by=booked_by,
        topic=topic,
        booked_at=timezone.now() if booked_by else None,
    )


def test_home_greets_by_first_name(client, asha):
    client.force_login(asha)

    html = client.get(reverse("home")).content.decode()

    assert ", Asha</h1>" in html


def test_home_lists_meetings_booked_both_ways(client, asha, vikram):
    make_slot(asha, 2, booked_by=vikram, topic="Q3 numbers")
    make_slot(vikram, 30, booked_by=asha, topic="Interview panel")
    client.force_login(asha)

    response = client.get(reverse("home"))

    meetings = response.context["meetings"]
    assert [m.topic for m in meetings] == ["Q3 numbers", "Interview panel"]
    assert all(m.other == vikram for m in meetings)


def test_home_leaves_out_free_cancelled_and_past_slots(client, asha, vikram):
    make_slot(asha, 2)
    cancelled = make_slot(asha, 3, booked_by=vikram, topic="Cancelled")
    cancelled.cancelled_at = timezone.now()
    cancelled.save()
    make_slot(asha, -2, booked_by=vikram, topic="Over")
    client.force_login(asha)

    response = client.get(reverse("home"))

    assert response.context["meetings"] == []
    assert "No meetings booked." in response.content.decode()


def test_home_needs_login(client):
    response = client.get(reverse("home"))

    assert response.status_code == 302


def test_home_lists_conferences_with_meetings(client, asha, django_user_model):
    from datetime import timedelta

    from meetings.services import create_conference

    host = django_user_model.objects.create_user(
        username="S900", first_name="Dev", password="pw"
    )
    start = timezone.now() + timedelta(days=1)
    create_conference(
        host, "Quarterly review", start, start + timedelta(hours=1), [asha]
    )
    client.force_login(asha)

    html = client.get(reverse("home")).content.decode()

    assert "Quarterly review" in html and "Conference · Dev" in html
