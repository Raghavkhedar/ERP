from datetime import timedelta
from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import AccessGrant, Company
from notifications.models import Notification
from people.models import Person

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


CALL = {
    "outcome": "reg_touch",
    "call_type": "inbound",
    "intention": "call",
    "notes": "ok",
}


def tomorrow():
    return timezone.now() + timedelta(days=1)


def test_new_number_opens_a_call_for_the_sourcer_but_a_duplicate_does_not(todo, caller):
    assert (todo.owner, todo.purpose, todo.status) == (caller, "call", "pending")
    source_number(todo.requisition, "Asha", "9876543210", caller)
    assert FollowUp.objects.count() == 1


def test_logging_closes_the_call_and_opens_the_next_with_its_intention(todo, caller):
    log_call(
        todo, "reg_not_attended", caller, next_due=tomorrow(), intention="interview"
    )
    todo.refresh_from_db()
    assert todo.status == "completed"
    assert FollowUp.objects.get(status="pending").purpose == "interview"
    assert CallLog.objects.get().outcome == "reg_not_attended"


def test_closed_follow_up_cannot_be_logged_twice(todo, caller):
    log_call(todo, "reg_touch", caller)
    with pytest.raises(FollowUpError):
        log_call(todo, "reg_touch", caller)
    assert CallLog.objects.count() == 1


def test_log_through_the_page(client, todo):
    r = client.post(
        reverse("hiring:followup_call", args=[todo.pk]),
        {
            **CALL,
            "next_due": "2030-01-02",
            "intention": "other",
            "intention_other": "Bring ID",
        },
    )
    assert r.status_code == 302
    nxt = FollowUp.objects.get(status="pending", due__year=2030)
    assert nxt.intention == "Bring ID"
    assert CallLog.objects.get().call_type == "inbound"


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
    log_call(todo, "reg_not_attended", caller, next_due=tomorrow())
    book = load_workbook(
        BytesIO(client.get(reverse("hiring:screening_export")).content)
    )
    assert len(list(book["Follow-ups"].values)) == 2
    assert list(book["Call log"].values)[1][3] == "Reg Call Not Attended"


def test_sheet_shows_summary_and_filters_by_column(client, todo):
    url = reverse("hiring:screening")
    page = client.get(url)
    assert page.context["summary"]["today"] == 1
    assert [f.stage for f in page.context["rows"]] == ["screening"]
    assert [f.tag_label for f in page.context["rows"]] == ["Not called yet"]
    assert len(client.get(url, {"q": "zzz"}).context["rows"]) == 0
    assert (
        len(
            client.get(url, {"q": "ash", "purpose": "call", "tag": "none"}).context[
                "rows"
            ]
        )
        == 1
    )
    assert len(client.get(url, {"tag": "interested"}).context["rows"]) == 0
    assert len(client.get(url, {"stage": "offered"}).context["rows"]) == 0
    assert len(client.get(url, {"due_from": "2999-01-01"}).context["rows"]) == 0


def post_call(client, todo, **extra):
    data = {**CALL, "next_due": "2030-01-02", **extra}
    return client.post(reverse("hiring:followup_call", args=[todo.pk]), data)


def test_next_date_cannot_be_before_today(client, todo):
    r = post_call(client, todo, next_due="2020-01-01")
    assert r.status_code == 200 and not CallLog.objects.exists()


def test_a_reschedule_needs_the_candidates_reason(client, todo):
    assert post_call(client, todo, rescheduled="on").status_code == 200
    assert not CallLog.objects.exists()
    post_call(client, todo, rescheduled="on", reschedule_reason="Has a wedding")
    call = CallLog.objects.get()
    assert (call.rescheduled, call.reschedule_reason) == (True, "Has a wedding")


def test_other_intention_needs_its_text(client, todo):
    assert post_call(client, todo, intention="other").status_code == 200
    assert not CallLog.objects.exists()


def test_discuss_and_department_change_notify_the_supervisor(
    client, todo, caller, django_user_model
):
    boss = django_user_model.objects.create_user(username="BOSS", password="pw")
    post_call(client, todo, discuss="on")  # no supervisor yet: refused with a message
    assert not CallLog.objects.exists()
    caller.supervisor = boss
    caller.save()
    post_call(client, todo, department_changed="on")
    assert CallLog.objects.get().department_changed
    assert Notification.objects.get(user=boss).text.endswith("Asha")


def test_calling_tab_lists_only_my_calls_and_screening_has_no_log_button(
    client, todo, django_user_model, senken
):
    other = member(django_user_model, senken, "S8")
    source_number(todo.requisition, "Ben", "9123456780", other)
    assert [
        f.person.name for f in client.get(reverse("hiring:calling")).context["rows"]
    ] == ["Asha"]
    assert (
        reverse("hiring:followup", args=[todo.pk])
        not in client.get(reverse("hiring:screening")).content.decode()
    )


def test_incoming_call_is_logged_for_a_picked_candidate(client, todo, caller):
    other = Person.objects.create(
        company=todo.person.company, name="Ravi", phone="9123456780"
    )
    found = client.get(reverse("hiring:calling_people"), {"q": "rav"}).json()["people"]
    assert [p["name"] for p in found] == ["Ravi"]
    assert (
        client.get(reverse("hiring:calling_people"), {"q": str(other.pk)}).json()[
            "people"
        ][0]["id"]
        == other.pk
    )
    r = client.post(
        reverse("hiring:call_new"),
        {**CALL, "person": other.pk, "next_due": "2030-01-02", "call_type": "inbound"},
    )
    assert r.status_code == 302
    call = CallLog.objects.get(person=other)
    assert (call.followup, call.call_type, call.caller) == (None, "inbound", caller)
    assert FollowUp.objects.get(person=other, status="pending").owner == caller


def test_incoming_call_needs_a_candidate(client, todo):
    r = client.post(reverse("hiring:call_new"), {**CALL, "next_due": "2030-01-02"})
    assert r.status_code == 200 and not CallLog.objects.exists()


def test_incoming_call_form_defaults_to_inbound(client, todo):
    form = client.get(reverse("hiring:call_new")).context["call_form"]
    assert form["call_type"].value() == "inbound"
