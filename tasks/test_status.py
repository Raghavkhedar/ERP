import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from chat.models import Message

from .models import Status
from .services import TaskError, add_update, allowed_statuses, assign, set_status

pytestmark = pytest.mark.django_db


def status_url(task):
    return reverse("tasks:status", args=[task.pk])


def test_admins_move_a_task_along(task, boss):
    for status in (Status.ONGOING, Status.DONE):
        set_status(task, boss, status)
        task.refresh_from_db()
        assert task.status == status


def test_office_admins_change_status_too(task, manager):
    set_status(task, manager, Status.DONE)

    task.refresh_from_db()
    assert task.status == Status.DONE


@pytest.mark.parametrize("status", list(Status))
def test_the_assignee_cannot_change_status(task, alice, status):
    assert allowed_statuses(task, alice) == []
    with pytest.raises(TaskError):
        set_status(task, alice, status)


def test_the_assignees_first_update_still_starts_the_task(task, alice):
    add_update(task, alice, "Started")

    task.refresh_from_db()
    assert task.status == Status.ONGOING


def test_marking_done_tells_the_assignee(task, boss, alice):
    set_status(task, boss, Status.DONE)

    notice = Message.objects.latest("id")
    assert notice.author == boss
    assert notice.body == "marked your task Done: Audit report for Q3"
    assert alice.pk in notice.conversation.memberships.values_list("user", flat=True)


def test_another_admin_marking_done_tells_the_assignee(task, manager, alice):
    set_status(task, manager, Status.DONE)

    notice = Message.objects.latest("id")
    assert notice.author == manager
    assert notice.body == "marked your task Done: Audit report for Q3"
    assert alice.pk in notice.conversation.memberships.values_list("user", flat=True)


def test_closing_tells_the_assignee(task, boss):
    set_status(task, boss, Status.CLOSED)

    task.refresh_from_db()
    assert task.status == Status.CLOSED
    assert task.closed_at is not None
    assert Message.objects.latest("id").body == "closed your task: Audit report for Q3"


def test_an_admins_own_task_sends_no_notice(boss, next_week):
    own = assign(boss, boss, 1, "My own job", next_week)

    set_status(own, boss, Status.DONE)

    assert not Message.objects.exists()


def test_reopening_clears_closed_at(task, boss):
    set_status(task, boss, Status.CLOSED)
    set_status(task, boss, Status.ONGOING)

    task.refresh_from_db()
    assert task.closed_at is None


def test_others_cannot_change_it(task, bob):
    with pytest.raises(PermissionDenied):
        set_status(task, bob, Status.DONE)


def test_the_status_buttons(client, task, boss):
    client.force_login(boss)

    response = client.post(status_url(task), {"status": "done"})

    assert response.status_code == 302
    task.refresh_from_db()
    assert task.status == Status.DONE


def test_the_assignee_sees_no_buttons_and_is_refused(client, task, alice):
    client.force_login(alice)

    page = client.get(reverse("tasks:detail", args=[task.pk]))
    response = client.post(status_url(task), {"status": "done"}, follow=True)

    assert b'name="status"' not in page.content
    assert b"Only an admin can change" in response.content
    task.refresh_from_db()
    assert task.status == Status.OPEN
