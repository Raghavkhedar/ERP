import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from chat.models import Message

from .models import Status
from .services import TaskError, allowed_statuses, set_status

pytestmark = pytest.mark.django_db


def status_url(task):
    return reverse("tasks:status", args=[task.pk])


def test_the_assignee_moves_their_task_along(task, alice):
    set_status(task, alice, Status.ONGOING)
    task.refresh_from_db()
    assert task.status == Status.ONGOING

    set_status(task, alice, Status.DONE)
    task.refresh_from_db()
    assert task.status == Status.DONE


def test_marking_done_tells_the_assigner(task, boss, alice):
    set_status(task, alice, Status.DONE)

    notice = Message.objects.latest("id")
    assert notice.author == alice
    assert notice.body == "finished a task: Audit report for Q3"
    assert boss.pk in notice.conversation.memberships.values_list("user", flat=True)


def test_the_assignee_cannot_close(task, alice):
    with pytest.raises(TaskError):
        set_status(task, alice, Status.CLOSED)

    assert Status.CLOSED not in allowed_statuses(task, alice)


def test_an_admin_closes_and_the_assignee_hears(task, boss, alice):
    set_status(task, boss, Status.CLOSED)

    task.refresh_from_db()
    assert task.status == Status.CLOSED
    assert task.closed_at is not None
    assert Message.objects.latest("id").body == "closed your task: Audit report for Q3"


def test_a_closed_task_is_locked_for_the_assignee(task, boss, alice):
    set_status(task, boss, Status.CLOSED)
    task.refresh_from_db()

    assert allowed_statuses(task, alice) == []
    with pytest.raises(TaskError):
        set_status(task, alice, Status.ONGOING)


def test_reopening_clears_closed_at(task, boss):
    set_status(task, boss, Status.CLOSED)
    set_status(task, boss, Status.ONGOING)

    task.refresh_from_db()
    assert task.closed_at is None


def test_others_cannot_change_it(task, bob):
    with pytest.raises(PermissionDenied):
        set_status(task, bob, Status.DONE)


def test_the_status_buttons(client, task, alice):
    client.force_login(alice)

    response = client.post(status_url(task), {"status": "ongoing"})

    assert response.status_code == 302
    task.refresh_from_db()
    assert task.status == Status.ONGOING


def test_closing_from_the_page_is_refused_for_the_assignee(client, task, alice):
    client.force_login(alice)

    response = client.post(status_url(task), {"status": "closed"}, follow=True)

    assert b"Only an admin can close" in response.content
    task.refresh_from_db()
    assert task.status == Status.OPEN
