from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from core.access import MODULES
from core.models import AccessGrant, Company
from people.models import Person

from .models import FollowUp, Requisition
from .services import shift_calls, source_number

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def user(client, django_user_model, senken):
    u = django_user_model.objects.create_user("ops", password="x")
    senken.memberships.create(user=u)
    for tab in MODULES["recruitment"].sections:
        AccessGrant.objects.create(
            user=u, company=senken, module="recruitment", section=tab
        )
    client.force_login(u)
    return u


@pytest.fixture
def req(senken, user):
    return Requisition.objects.create(
        company=senken, department="sales", profile="Rep", headcount=3, opened_by=user
    )


def test_shift_calls_keeps_time_and_counts_the_move(req, user):
    for n in range(2):
        source_number(req, f"P{n}", f"99999 0000{n}", user)
    rows = FollowUp.objects.all()
    original = {f.pk: timezone.localtime(f.due).time() for f in rows}
    assert shift_calls(rows, date(2031, 5, 1), "holiday") == 2
    for f in FollowUp.objects.all():
        assert timezone.localtime(f.due).date() == date(2031, 5, 1)
        assert timezone.localtime(f.due).time() == original[f.pk]
        assert f.reschedule_count == 1 and f.original_due


def test_shift_leaves_interviews_alone(req, user):
    person = source_number(req, "Ravi", "99999 11111", user).person
    interview = FollowUp.objects.create(
        person=person, purpose="interview", due=timezone.now(), owner=user
    )
    assert (
        shift_calls(
            FollowUp.objects.filter(pk=interview.pk), date(2031, 5, 1), "holiday"
        )
        == 0
    )
    interview.refresh_from_db()
    assert interview.reschedule_count == 0


def test_shift_view_moves_a_group(req, user, client):
    source_number(req, "Ravi", "99999 11111", user)
    page = client.get(reverse("hiring:screening"))
    assert b"Move all calls" in page.content
    client.post(
        reverse("hiring:shift"),
        {"group": "later", "day": "2031-05-01", "reason": "shortage"},
    )
    due = FollowUp.objects.get().due
    assert timezone.localtime(due).date() == date(2031, 5, 1)
    client.post(reverse("hiring:shift"), {"group": "today", "day": "", "reason": ""})
    assert timezone.localtime(FollowUp.objects.get().due).date() == date(2031, 5, 1)


def test_call_alarm_rings_until_snoozed_or_done(req, user, client):
    from .services import due_call_alarms, next_call_alarm_in

    source_number(req, "Ravi", "99999 11111", user)
    call = FollowUp.objects.get()
    call.due = timezone.now() - timedelta(minutes=1)
    call.save()
    assert list(due_call_alarms(user)) == [call]
    ring = client.get(reverse("tasks:alarms")).json()["alarms"]
    assert (
        ring[0]["id"] == f"call-{call.pk}"
        and ring[0]["label"] == "Normal follow-up alarm"
    )

    client.post(
        reverse("hiring:followup_snooze", args=[call.pk]),
        {"action": "snooze", "length": "10m"},
    )
    assert list(due_call_alarms(user)) == []
    assert 0 < next_call_alarm_in(user) <= 600

    call.refresh_from_db()
    assert call.snoozed_until


def test_only_the_owner_can_snooze(req, user, client, django_user_model, senken):
    source_number(req, "Ravi", "99999 11111", user)
    call = FollowUp.objects.get()
    other = django_user_model.objects.create_user("o", password="x")
    senken.memberships.create(user=other)
    for tab in MODULES["recruitment"].sections:
        AccessGrant.objects.create(
            user=other, company=senken, module="recruitment", section=tab
        )
    from .services import FollowUpError, snooze_call

    with pytest.raises(FollowUpError):
        snooze_call(call, other, "1h")


def test_shift_preview_lists_who_moves_and_obeys_filters(req, user, client):
    source_number(req, "Ravi", "99999 11111", user)
    source_number(req, "Asha", "99999 22222", user)
    before = list(FollowUp.objects.order_by("pk").values_list("due", flat=True))
    data = {"group": "all", "day": "2031-05-01", "reason": "shortage", "preview": "1"}
    page = client.post(reverse("hiring:shift"), {**data, "filters": "q=Ravi"})
    assert b"1 call will move" in page.content and b"Asha" not in page.content
    assert list(FollowUp.objects.order_by("pk").values_list("due", flat=True)) == before
    client.post(
        reverse("hiring:shift"),
        {
            "group": "all",
            "day": "2031-05-01",
            "reason": "shortage",
            "filters": "q=Ravi",
        },
    )
    moved = FollowUp.objects.get(person__name="Ravi")
    assert timezone.localtime(moved.due).date() == date(2031, 5, 1)
    assert timezone.localtime(
        FollowUp.objects.get(person__name="Asha").due
    ).date() != date(2031, 5, 1)


def test_shift_preview_narrows_by_preference_and_department(req, user, client):
    source_number(req, "Ravi", "99999 11111", user)
    source_number(req, "Asha", "99999 22222", user)
    Person.objects.filter(name="Ravi").update(priority="preferred")
    data = {
        "group": "all",
        "day": "2031-05-01",
        "reason": "shortage",
        "preview": "1",
        "refined": "1",
        "priority": "preferred",
    }
    page = client.post(reverse("hiring:shift"), data)
    assert b"1 call will move" in page.content and b"Asha" not in page.content
    data["department"] = "no-such-department"
    page = client.post(reverse("hiring:shift"), data)
    assert b"0 calls will move" in page.content


def test_confirming_with_the_popups_filters_replaces_the_page_filters(
    req, user, client
):
    source_number(req, "Ravi", "99999 11111", user)
    source_number(req, "Asha", "99999 22222", user)
    Person.objects.filter(name="Ravi").update(priority="preferred")
    client.post(
        reverse("hiring:shift"),
        {
            "group": "all",
            "day": "2031-05-01",
            "reason": "shortage",
            "filters": "q=Asha",  # the page's filter, replaced by the dialog's
            "refined": "1",
            "priority": "preferred",
        },
    )

    def moved(name):
        due = FollowUp.objects.get(person__name=name).due
        return timezone.localtime(due).date() == date(2031, 5, 1)

    assert moved("Ravi") and not moved("Asha")
