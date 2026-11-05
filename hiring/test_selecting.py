from datetime import timedelta
from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import AccessGrant, Company

from .models import FollowUp, HRAssessment, Interview, Requisition
from .services import FollowUpError, log_call, record_interview, source_number

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


def member(django_user_model, senken, name, *sections):
    user = django_user_model.objects.create_user(username=name, password="pw")
    senken.memberships.create(user=user)
    for section in sections:
        AccessGrant.objects.create(
            user=user, company=senken, module="recruitment", section=section
        )
    return user


@pytest.fixture
def caller(client, django_user_model, senken):
    user = member(django_user_model, senken, "S9", "candidates")
    client.force_login(user)
    return user


@pytest.fixture
def booked(senken, caller):
    req = Requisition.objects.create(
        company=senken, opened_by=caller, department="bo", profile="Fitter", headcount=2
    )
    source_number(req, "Asha", "9876543210", caller)
    log_call(
        FollowUp.objects.get(),
        "interview",
        caller,
        next_due=timezone.now() + timedelta(days=1),
    )
    return FollowUp.objects.get(status="pending", purpose="interview")


def test_selected_records_the_interview_and_opens_an_offer(booked, caller):
    record_interview(booked, "selected", caller, questions="PLC?")
    interview = Interview.objects.get()
    assert (interview.result, interview.scheduled_at) == ("selected", booked.due)
    assert interview.requisition == booked.requisition
    assert FollowUp.objects.filter(status="pending", purpose="offer").count() == 1


def test_hold_needs_a_date_to_open_a_call_and_rejected_opens_nothing(booked, caller):
    record_interview(booked, "hold", caller)
    assert not FollowUp.objects.filter(status="pending").exists()


def test_hold_with_a_date_opens_a_call(booked, caller):
    record_interview(booked, "hold", caller, next_due=timezone.now())
    assert FollowUp.objects.get(status="pending").purpose == "call"


def test_an_interview_cannot_be_recorded_twice(booked, caller):
    record_interview(booked, "rejected", caller)
    with pytest.raises(FollowUpError):
        record_interview(booked, "selected", caller)
    assert Interview.objects.count() == 1


def test_record_through_the_page(client, booked):
    r = client.post(
        reverse("hiring:interview", args=[booked.pk]), {"result": "selected"}
    )
    assert r.status_code == 302 and Interview.objects.exists()
    page = client.get(reverse("hiring:selecting")).content.decode()
    assert "Selected" in page and "Add HR notes" not in page


def test_hr_notes_only_for_those_granted_the_section(
    client, booked, caller, django_user_model, senken
):
    record_interview(booked, "selected", caller)
    pk = Interview.objects.get().pk
    assert client.get(reverse("hiring:assess", args=[pk])).status_code == 403
    hr = member(django_user_model, senken, "S5", "candidates", "assessments")
    client.force_login(hr)
    assert b"Add HR notes" in client.get(reverse("hiring:selecting")).content
    r = client.post(
        reverse("hiring:assess", args=[pk]),
        {"decision": "selected", "level": "expert", "comments": "sharp"},
    )
    assert r.status_code == 302
    assert HRAssessment.objects.get().level == "expert"


def test_export_hides_hr_from_non_hr(client, booked, caller):
    record_interview(booked, "selected", caller)
    book = load_workbook(
        BytesIO(client.get(reverse("hiring:selecting_export")).content)
    )
    assert book.sheetnames == ["Interviews"]
