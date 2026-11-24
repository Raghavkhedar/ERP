from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.access import MODULES
from core.models import AccessGrant, Company

from .models import FollowUp, Interview, Offer, Requisition
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
    django_user_model.objects.create_user("under", supervisor=user)  # supervises
    client.force_login(user)
    return user


def walk(req, user, phone, name, to):
    """Take one candidate as far as `to`: call, interview, offer, join."""
    source_number(req, name, phone, user)
    todo = FollowUp.objects.get(person__phone=phone, status="pending")
    log_call(
        todo,
        "reg_ff",
        user,
        next_due=timezone.now() + timedelta(days=1),
        intention="interview",
    )
    if to == "called":
        return
    record_interview(
        FollowUp.objects.get(person__phone=phone, purpose="interview"),
        "selected",
        user,
    )
    if to == "selected":
        return
    interview = Interview.objects.get(person__phone=phone)
    offer = start_offer(interview, Decimal("1"), user, timezone.now())
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


def test_timeline_and_card(client, senken, boss):
    req = Requisition.objects.create(
        company=senken, department="sales", profile="Rep", headcount=1, opened_by=boss
    )
    for tab in MODULES["recruitment"].sections:
        AccessGrant.objects.get_or_create(
            user=boss, company=senken, module="recruitment", section=tab
        )
    person = source_number(req, "Ravi", "99999 11111", boss, "Naukri").person
    log_call(
        person.followups.get(),
        "reg_not_attended",
        boss,
        notes="Keen",
        next_due=timezone.now() + timedelta(days=1),
    )
    person.name = "Ravi K"
    person.version += 1
    person.save()
    from .services import timeline

    texts = [t for _, _, t in timeline(person)]
    assert "Card created" in texts
    assert any("via Naukri" in t for t in texts)
    assert any(t.startswith("Call: Reg Call Not Attended. Keen") for t in texts)
    assert "Edited name" in texts
    page = client.get(reverse("people:detail", args=[person.pk]))
    assert page.status_code == 200 and b"Timeline" in page.content


def test_call_form_shows_timeline_with_calls_on_hover(client, senken, boss):
    req = Requisition.objects.create(
        company=senken, department="sales", profile="Rep", headcount=1, opened_by=boss
    )
    for tab in MODULES["recruitment"].sections:
        AccessGrant.objects.get_or_create(
            user=boss, company=senken, module="recruitment", section=tab
        )
    person = source_number(req, "Ravi", "99999 11111", boss, "Naukri").person
    log_call(
        person.followups.get(),
        "reg_not_attended",
        boss,
        notes="Keen on night shift",
        next_due=timezone.now() + timedelta(days=1),
    )
    person.followups.filter(status="pending").update(owner=boss)
    client.force_login(boss)
    page = client.get(
        reverse("hiring:followup", args=[person.followups.get(status="pending").pk])
    )
    body = page.content.decode()
    assert "Card created" in body
    # headline in the line, full notes only in the hover card
    assert ">Call: Reg Call Not Attended</p>" in body
    assert "Call: Reg Call Not Attended. Keen on night shift</div>" in body
    # offers stay off the call page but show on the card
    Offer.objects.create(person=person, requisition=req, made_by=boss)
    call = reverse("hiring:followup", args=[person.followups.get(status="pending").pk])
    Interview.objects.create(
        person=person,
        requisition=req,
        interviewer=boss,
        scheduled_at=timezone.now(),
        result="hold_cftl",
        notes="Secret",
    )
    on_call_page = client.get(call).content.decode()
    assert "Offer made" not in on_call_page and "Secret" not in on_call_page
    card = client.get(reverse("people:detail", args=[person.pk])).content.decode()
    assert (
        "Offer made" in card
        and "Secret" in card
        and "Keen on night shift</div>" in card
    )
