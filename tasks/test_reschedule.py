from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from .models import DateChange
from .services import TaskError, reschedule

pytestmark = pytest.mark.django_db


@pytest.fixture
def lead(django_user_model, alice):
    user = django_user_model.objects.create_user(
        username="lead", first_name="lead", password="pw"
    )
    alice.supervisor = user
    alice.save()
    return user


def test_admin_moves_the_date_later_and_earlier_with_a_reason(task, boss):
    original = task.due_date
    reschedule(task, boss, original + timedelta(days=3), "Waiting on the bank")
    task.refresh_from_db()
    assert task.due_date == original + timedelta(days=3)

    reschedule(task, boss, original - timedelta(days=2), "Client needs it sooner")
    task.refresh_from_db()
    assert task.due_date == original - timedelta(days=2)
    assert DateChange.objects.filter(task=task).count() == 2
    change = DateChange.objects.first()
    assert (change.old_date, change.reason) == (
        original + timedelta(days=3),
        "Client needs it sooner",
    )


def test_a_supervisor_moves_a_reports_date(task, lead):
    reschedule(task, lead, task.due_date + timedelta(days=1), "Holiday")
    assert DateChange.objects.get().changed_by == lead


def test_a_reason_is_required(task, boss):
    with pytest.raises(TaskError):
        reschedule(task, boss, task.due_date + timedelta(days=1), "  ")
    assert not DateChange.objects.exists()


def test_the_assignee_cannot_move_the_date(task, alice):
    with pytest.raises(PermissionDenied):
        reschedule(task, alice, task.due_date + timedelta(days=1), "More time")


def test_the_view_changes_the_date(client, task, boss):
    client.force_login(boss)
    new = task.due_date + timedelta(days=4)
    response = client.post(
        reverse("tasks:date", args=[task.pk]),
        {"due_date": new.isoformat(), "reason": "Slipped"},
    )
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.due_date == new


def test_the_view_refuses_a_missing_reason(client, task, boss):
    client.force_login(boss)
    old = task.due_date
    client.post(
        reverse("tasks:date", args=[task.pk]),
        {"due_date": (old + timedelta(days=4)).isoformat(), "reason": ""},
    )
    task.refresh_from_db()
    assert task.due_date == old
