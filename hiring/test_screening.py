from datetime import timedelta
from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import AccessGrant, Company
from notifications.models import Notification

from .models import CallLog, FollowUp, Requisition
from .services import FollowUpError, log_call, source_number

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


def member(django_user_model, senken, name):
    user = django_user_model.objects.create_user(username=name, password="pw")
    senken.memberships.create(user=user)
    AccessGrant.objects.create(
        user=user, company=senken, module="recruitment", section="candidates"
    )
    return user


@pytest.fixture
def caller(client, django_user_model, senken):
    user = member(django_user_model, senken, "S9")
    client.force_login(user)
    return user


@pytest.fixture
def todo(senken, caller):
    req = Requisition.objects.create(
        company=senken, opened_by=caller, department="bo", profile="Fitter", headcount=3
    )
    source_number(req, "Asha", "9876543210", caller)
    return FollowUp.objects.get()


def tomorrow():
    return timezone.now() + timedelta(days=1)


def test_new_number_opens_a_call_for_the_sourcer_but_a_duplicate_does_not(todo, caller):
    assert (todo.owner, todo.purpose, todo.status) == (caller, "call", "pending")
    source_number(todo.requisition, "Asha", "9876543210", caller)
    assert FollowUp.objects.count() == 1


def test_no_answer_closes_the_call_and_opens_the_next(todo, caller):
    log_call(todo, "no_answer", caller, next_due=tomorrow())
    todo.refresh_from_db()
    assert todo.status == "completed"
    assert FollowUp.objects.filter(status="pending").count() == 1
    assert CallLog.objects.get().outcome == "no_answer"


def test_a_date_is_required_when_a_next_call_is_due(todo, caller):
    with pytest.raises(FollowUpError):
        log_call(todo, "call_back", caller)
    assert not CallLog.objects.exists()


def test_interview_booking_opens_an_interview_follow_up(todo, caller):
    log_call(todo, "interview", caller, next_due=tomorrow())
    assert FollowUp.objects.get(status="pending").purpose == "interview"


def test_not_interested_ends_it_and_do_not_call_marks_the_card(todo, caller):
    log_call(todo, "do_not_call", caller)
    todo.person.refresh_from_db()
    assert todo.person.contact_status == "do_not_call"
    assert not FollowUp.objects.filter(status="pending").exists()


def test_closed_follow_up_cannot_be_logged_twice(todo, caller):
    log_call(todo, "not_interested", caller)
    with pytest.raises(FollowUpError):
        log_call(todo, "not_interested", caller)
    assert CallLog.objects.count() == 1


def test_log_through_the_page(client, todo):
    r = client.post(
        reverse("hiring:followup_call", args=[todo.pk]),
        {"outcome": "call_back", "next_due": "2030-01-02T10:00", "notes": "later"},
    )
    assert r.status_code == 302
    assert FollowUp.objects.filter(status="pending", due__year=2030).exists()


def test_reschedule_keeps_the_original_date(client, todo):
    first = todo.due
    client.post(
        reverse("hiring:followup_reschedule", args=[todo.pk]),
        {"due": "2030-01-02T10:00", "reason": "holiday"},
    )
    todo.refresh_from_db()
    assert (todo.original_due, todo.reschedule_count) == (first, 1)


def test_cancel(client, todo):
    client.post(reverse("hiring:followup_cancel", args=[todo.pk]))
    todo.refresh_from_db()
    assert todo.status == "cancelled"


def test_caller_sees_only_their_own_and_cannot_reassign(
    client, todo, django_user_model, senken
):
    other = member(django_user_model, senken, "S8")
    client.force_login(other)
    assert b"Asha" not in client.get(reverse("hiring:screening")).content
    assert client.get(reverse("hiring:followup", args=[todo.pk])).status_code == 404


def test_supervisor_reassigns_and_owner_is_told(
    client, todo, django_user_model, senken
):
    boss = member(django_user_model, senken, "S1")
    todo.owner.supervisor = boss
    todo.owner.save()
    client.force_login(boss)
    r = client.post(
        reverse("hiring:followup_reassign", args=[todo.pk]), {"owner": boss.pk}
    )
    assert r.status_code == 302
    todo.refresh_from_db()
    assert todo.owner == boss and todo.reassigned_from.username == "S9"
    assert Notification.objects.filter(user=boss).exists()


def test_export(client, todo, caller):
    log_call(todo, "no_answer", caller, next_due=tomorrow())
    book = load_workbook(
        BytesIO(client.get(reverse("hiring:screening_export")).content)
    )
    assert len(list(book["Follow-ups"].values)) == 2
    assert list(book["Call log"].values)[1][3] == "No answer"
