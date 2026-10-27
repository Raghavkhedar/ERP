from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from .models import Repeat, Status, Task
from .services import (
    TaskError,
    assign,
    dismiss_alarm,
    due_alarms,
    set_alarm,
    set_status,
    snooze_alarm,
)

pytestmark = pytest.mark.django_db

JSON = {"HTTP_ACCEPT": "application/json"}


def ringing(task, **fields):
    Task.objects.filter(pk=task.pk).update(
        remind_at=timezone.now() - timedelta(minutes=1), **fields
    )
    task.refresh_from_db()
    return task


def test_anyone_can_give_themselves_a_task(alice, next_week):
    task = assign(alice, alice, 5, "Renew the licence", next_week)
    assert task.assigned_to == alice == task.assigned_by


def test_only_admins_assign_to_other_people(alice, bob, next_week):
    with pytest.raises(PermissionDenied):
        assign(alice, bob, 5, "Do my work", next_week)


def test_employee_adds_a_task_for_themselves(client, alice, next_week):
    client.force_login(alice)
    response = client.post(
        reverse("tasks:new"),
        {
            "priority": "4",
            "description": "Call the CA",
            "due_date": next_week.isoformat(),
        },
    )
    assert response.status_code == 302
    task = Task.objects.get()
    assert task.assigned_to == alice == task.assigned_by


def test_employee_cannot_pick_someone_else_in_the_form(client, alice, bob, next_week):
    client.force_login(alice)
    client.post(
        reverse("tasks:new"),
        {
            "assigned_to": bob.pk,
            "priority": "4",
            "description": "Call the CA",
            "due_date": next_week.isoformat(),
        },
    )
    assert Task.objects.get().assigned_to == alice


def test_owner_of_a_personal_task_can_mark_it_done(alice, next_week):
    task = assign(alice, alice, 5, "Renew the licence", next_week)
    assert set_status(task, alice, Status.DONE).status == Status.DONE


def test_assignee_still_cannot_mark_an_admins_task_done(task, alice):
    with pytest.raises(TaskError):
        set_status(task, alice, Status.DONE)


def test_alarm_can_be_set_when_adding_a_task(boss, alice, next_week):
    at = timezone.now() + timedelta(hours=2)
    task = assign(
        boss, alice, 3, "Audit", next_week, remind_at=at, remind_every="daily"
    )
    assert task.remind_at == at
    assert task.remind_every == Repeat.DAILY


def test_alarm_in_the_past_is_refused(task, alice):
    with pytest.raises(TaskError):
        set_alarm(task, alice, timezone.now() - timedelta(minutes=5))


def test_alarm_rings_only_for_the_assignee_once_due(task, alice, boss):
    set_alarm(task, alice, timezone.now() + timedelta(hours=1))
    assert not due_alarms(alice).exists()
    ringing(task)
    assert list(due_alarms(alice)) == [task]
    assert not due_alarms(boss).exists()


def test_alarm_stops_when_the_task_is_done(task, alice, boss):
    ringing(task)
    set_status(task, boss, Status.DONE)
    assert not due_alarms(alice).exists()


def test_snooze_moves_the_alarm_later(task, alice):
    ringing(task)
    snooze_alarm(task, alice, "1h")
    task.refresh_from_db()
    assert not due_alarms(alice).exists()
    assert task.remind_at > timezone.now() + timedelta(minutes=59)


def test_snooze_tomorrow_is_nine_in_the_morning(task, alice):
    ringing(task)
    snooze_alarm(task, alice, "tomorrow")
    task.refresh_from_db()
    local = timezone.localtime(task.remind_at)
    assert local.hour == 9
    assert local.date() > timezone.localdate()


def test_dismissing_a_one_off_alarm_ends_it(task, alice):
    ringing(task)
    dismiss_alarm(task, alice)
    task.refresh_from_db()
    assert task.remind_at is None


def test_dismissing_a_repeating_alarm_sets_the_next_ring(task, alice):
    ringing(task, remind_every="weekly")
    dismiss_alarm(task, alice)
    task.refresh_from_db()
    assert task.remind_at > timezone.now()
    assert task.remind_at < timezone.now() + timedelta(weeks=1, minutes=1)


def test_dismissing_twice_does_not_clear_a_snoozed_alarm(task, alice):
    ringing(task)
    snooze_alarm(task, alice, "10m")
    dismiss_alarm(task, alice)
    task.refresh_from_db()
    assert task.remind_at is not None


def test_someone_else_cannot_touch_the_alarm(task, bob):
    with pytest.raises(PermissionDenied):
        set_alarm(task, bob, timezone.now() + timedelta(hours=1))


def test_alarms_endpoint_lists_what_is_ringing(client, task, alice):
    ringing(task)
    client.force_login(alice)
    data = client.get(reverse("tasks:alarms")).json()
    assert [a["id"] for a in data["alarms"]] == [task.pk]
    assert data["alarms"][0]["action"] == reverse("tasks:alarm", args=[task.pk])


def test_snooze_through_the_endpoint(client, task, alice):
    ringing(task)
    client.force_login(alice)
    response = client.post(
        reverse("tasks:alarm", args=[task.pk]),
        {"action": "snooze", "length": "10m"},
        **JSON,
    )
    assert response.json() == {"ok": True}
    assert client.get(reverse("tasks:alarms")).json()["alarms"] == []


def test_set_and_clear_from_the_detail_page(client, task, alice):
    client.force_login(alice)
    url = reverse("tasks:alarm", args=[task.pk])
    later = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    client.post(url, {"action": "set", "remind_at": later, "remind_every": "daily"})
    task.refresh_from_db()
    assert task.remind_at and task.remind_every == "daily"
    client.post(url, {"action": "clear"})
    task.refresh_from_db()
    assert task.remind_at is None
    assert task.remind_every == ""


def test_other_peoples_tasks_404_on_the_alarm_endpoint(client, task, bob):
    client.force_login(bob)
    response = client.post(
        reverse("tasks:alarm", args=[task.pk]), {"action": "dismiss"}
    )
    assert response.status_code == 404
