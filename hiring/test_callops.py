from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from core.access import MODULES
from core.models import AccessGrant, Company
from people.models import Person

from .models import FollowUp, Requisition
from .services import bulk_move, source_number

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
    assert bulk_move(rows, date(2031, 5, 1), "holiday") == 2
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
        bulk_move(FollowUp.objects.filter(pk=interview.pk), date(2031, 5, 1), "holiday")
        == 0
    )
    interview.refresh_from_db()
    assert interview.reschedule_count == 0


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


def _all(**extra):
    return {
        "scope": "all",
        "do": "move",
        "day": "2031-05-01",
        "reason": "shortage",
        **extra,
    }


def _due(name):
    return timezone.localtime(FollowUp.objects.get(person__name=name).due).date()


def test_the_screening_page_has_one_set_of_move_options(req, user, client):
    source_number(req, "Ravi", "99999 11111", user)
    page = client.get(reverse("hiring:screening"))
    assert b"Move all calls" not in page.content
    assert b'name="when"' in page.content and b'name="priority"' in page.content


def test_move_preview_lists_who_moves_and_writes_nothing(req, user, client):
    user.is_superuser = True
    user.save()
    source_number(req, "Ravi", "99999 11111", user)
    source_number(req, "Asha", "99999 22222", user)
    before = list(FollowUp.objects.order_by("pk").values_list("due", flat=True))
    page = client.post(reverse("hiring:bulk"), _all(preview="1", filters="q=Ravi"))
    assert b"1 call will move" in page.content and b"Asha" not in page.content
    assert list(FollowUp.objects.order_by("pk").values_list("due", flat=True)) == before
    client.post(reverse("hiring:bulk"), _all(filters="q=Ravi"))
    assert _due("Ravi") == date(2031, 5, 1) and _due("Asha") != date(2031, 5, 1)


def test_preview_and_move_obey_the_preference_and_when_filters(req, user, client):
    user.is_superuser = True
    user.save()
    source_number(req, "Ravi", "99999 11111", user)
    source_number(req, "Asha", "99999 22222", user)
    Person.objects.filter(name="Ravi").update(priority="preferred")
    page = client.post(
        reverse("hiring:bulk"), _all(preview="1", filters="priority=preferred")
    )
    assert b"1 call will move" in page.content and b"Asha" not in page.content
    page = client.post(
        reverse("hiring:bulk"), _all(preview="1", filters="when=overdue")
    )
    assert b"0 calls will move" in page.content
    client.post(reverse("hiring:bulk"), _all(filters="priority=preferred"))
    assert _due("Ravi") == date(2031, 5, 1) and _due("Asha") != date(2031, 5, 1)


def test_preview_of_ticked_calls_carries_their_ids_to_the_confirm(req, user, client):
    user.is_superuser = True
    user.save()
    source_number(req, "Ravi", "99999 11111", user)
    source_number(req, "Asha", "99999 22222", user)
    ravi = FollowUp.objects.get(person__name="Ravi")
    page = client.post(
        reverse("hiring:bulk"),
        _all(scope="ticked", preview="1", ids=[ravi.pk]),
    )
    assert b"1 call will move" in page.content
    assert f'name="ids" value="{ravi.pk}"'.encode() in page.content


def test_preview_says_what_is_wrong_with_the_choices(req, user, client):
    user.is_superuser = True
    user.save()
    source_number(req, "Ravi", "99999 11111", user)
    page = client.post(reverse("hiring:bulk"), _all(preview="1", day=""))
    assert b"Pick a day" in page.content


def _next_sunday():
    today = timezone.localdate()
    return today + timedelta(days=(6 - today.weekday()) % 7 or 7)


def test_a_sunday_is_refused_and_a_move_onto_one_lands_on_monday(req, user):
    from .forms import BulkForm, RescheduleForm
    from .services import bulk_move

    sunday = _next_sunday()
    assert "due" in RescheduleForm({"due": sunday.isoformat(), "reason": "x"}).errors
    assert (
        "day"
        in BulkForm(
            {"scope": "all", "do": "move", "day": sunday.isoformat(), "reason": "x"},
            companies=Company.objects.all(),
        ).errors
    )

    person = Person.objects.create(company=req.company, name="A", phone="9000000001")
    call = FollowUp.objects.create(
        person=person, purpose=FollowUp.Purpose.CALL, due=timezone.now(), owner=user
    )
    bulk_move(FollowUp.objects.filter(pk=call.pk), sunday, "x")
    call.refresh_from_db()
    assert timezone.localtime(call.due).date() == sunday + timedelta(days=1)
