from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .services import assign

pytestmark = pytest.mark.django_db

LIST_URL = reverse("tasks:list")


def detail_url(task):
    return reverse("tasks:detail", args=[task.pk])


def edit_url(task):
    return reverse("tasks:edit", args=[task.pk])


def test_employees_see_only_their_own_tasks(client, task, boss, bob, next_week):
    bobs = assign(boss, bob, 1, "Vendor KYC", next_week)
    client.force_login(bob)

    response = client.get(LIST_URL)

    assert list(response.context["tasks"]) == [bobs]
    assert b"Add task" not in response.content


def test_assigners_see_everyones_tasks(client, task, boss, bob, next_week):
    bobs = assign(boss, bob, 1, "Vendor KYC", next_week)
    client.force_login(boss)

    response = client.get(LIST_URL)

    assert list(response.context["tasks"]) == [bobs, task]  # by priority
    assert b"Add task" in response.content


def test_someone_elses_task_is_not_found(client, task, bob):
    client.force_login(bob)

    assert client.get(detail_url(task)).status_code == 404
    assert client.post(reverse("tasks:status", args=[task.pk])).status_code == 404


def test_the_assignee_sees_the_task_but_cannot_edit(client, task, alice):
    client.force_login(alice)

    assert client.get(detail_url(task)).status_code == 200
    assert client.get(edit_url(task)).status_code == 403


def test_an_admin_edits_a_task(client, task, manager):
    client.force_login(manager)
    data = {
        "assigned_to": task.assigned_to_id,
        "priority": "1",
        "description": "Audit report, urgent",
        "due_date": (timezone.localdate() + timedelta(days=2)).isoformat(),
    }

    client.post(edit_url(task), data)

    task.refresh_from_db()
    assert task.priority == 1
    assert task.description == "Audit report, urgent"
