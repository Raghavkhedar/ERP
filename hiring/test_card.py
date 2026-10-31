from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import AccessGrant, Company

from .models import FollowUp, Requisition
from .services import (
    FollowUpError,
    accept,
    log_call,
    mark_joined,
    record_interview,
    schedule_call,
    source_number,
    stage,
    start_offer,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def user(client, django_user_model, senken):
    u = django_user_model.objects.create_user("card", password="x")
    senken.memberships.create(user=u)
    AccessGrant.objects.create(
        user=u, company=senken, module="recruitment", section="candidates"
    )
    client.force_login(u)
    return u


@pytest.fixture
def req(senken, user):
    return Requisition.objects.create(
        company=senken, department="sales", profile="Rep", headcount=1, opened_by=user
    )


def test_stage_follows_the_candidate(req, user):
    person = source_number(req, "Ravi", "99999 11111", user).person
    assert stage(person) == "Screening"  # a call is already booked
    tomorrow = timezone.now() + timedelta(days=1)
    log_call(person.followups.get(), "interview", user, next_due=tomorrow)
    assert stage(person) == "Selecting"
    record_interview(person.followups.get(purpose="interview"), "selected", user)
    assert stage(person) == "Hiring"
    offer = start_offer(person.followups.get(purpose="offer"), Decimal("1"), user)
    accept(offer, date(2030, 1, 6), user)
    assert stage(person) == "On-Boarding"
    mark_joined(offer, date(2030, 1, 6))
    assert stage(person) == "Working"


def test_schedule_call_once_per_card(req, user, client):
    person = source_number(req, "Ravi", "99999 11111", user).person
    with pytest.raises(FollowUpError):
        schedule_call(person, timezone.now(), user)
    person.followups.get().delete()
    call = schedule_call(person, timezone.now() + timedelta(days=2), user)
    assert call.requisition == req and call.owner == user
    page = client.get(reverse("people:detail", args=[person.pk]))
    assert b"Book a call" in page.content and b"Screening" in page.content


def test_schedule_call_view(req, user, client):
    person = source_number(req, "Ravi", "99999 11111", user).person
    FollowUp.objects.filter(person=person).delete()
    client.post(
        reverse("hiring:schedule_call", args=[person.pk]), {"due": "2031-01-02T10:00"}
    )
    assert person.followups.get().purpose == "call"
