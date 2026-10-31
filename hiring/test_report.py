from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import AccessGrant, Company

from .models import FollowUp, Requisition
from .services import (
    accept,
    funnel,
    log_call,
    mark_joined,
    record_interview,
    source_number,
    start_offer,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def boss(client, django_user_model, senken):
    user = django_user_model.objects.create_user(username="S9", password="pw")
    senken.memberships.create(user=user)
    AccessGrant.objects.create(
        user=user, company=senken, module="recruitment", section="openings"
    )
    client.force_login(user)
    return user


def walk(req, user, phone, name, to):
    """Take one candidate as far as `to`: call, interview, offer, join."""
    source_number(req, name, phone, user)
    todo = FollowUp.objects.get(person__phone=phone, status="pending")
    log_call(todo, "interview", user, next_due=timezone.now() + timedelta(days=1))
    if to == "called":
        return
    record_interview(
        FollowUp.objects.get(person__phone=phone, purpose="interview"),
        "selected",
        user,
    )
    if to == "selected":
        return
    offer = start_offer(
        FollowUp.objects.get(person__phone=phone, purpose="offer"), Decimal("1"), user
    )
    if to == "offered":
        return
    accept(offer, date(2030, 1, 6), user)
    mark_joined(offer, date(2030, 1, 6))


def test_funnel_counts_each_person_once_per_step(senken, boss):
    req = Requisition.objects.create(
        company=senken, opened_by=boss, department="bo", profile="Fitter", headcount=2
    )
    walk(req, boss, "9000000001", "A", "called")
    walk(req, boss, "9000000002", "B", "selected")
    walk(req, boss, "9000000003", "C", "joined")
    source_number(req, "A again", "9000000001", boss)  # a duplicate
    r = funnel([senken]).get()
    assert (r.sourced_n, r.duplicate_n, r.called_n) == (4, 1, 3)
    assert (r.interviewed_n, r.selected_n) == (2, 2)
    assert (r.offered_n, r.accepted_n, r.joined_n) == (1, 1, 1)


def test_page_and_export(client, senken, boss):
    req = Requisition.objects.create(
        company=senken, opened_by=boss, department="bo", profile="Fitter", headcount=1
    )
    walk(req, boss, "9000000003", "C", "joined")
    page = client.get(reverse("hiring:report")).content.decode()
    assert "Fitter" in page and "Joined" in page
    book = load_workbook(BytesIO(client.get(reverse("hiring:report_export")).content))
    assert list(book["Funnel"].values)[1][3:] == (1, 1, 0, 1, 1, 1, 1, 1, 1)
