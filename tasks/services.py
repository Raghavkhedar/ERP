from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from chat.services import post_notice

from .models import Status, Task


class TaskError(Exception):
    """A request that breaks a task rule; the message is shown to the user."""


def can_assign(user):
    return user.is_office_admin


def visible_tasks(user):
    """Everyone's tasks for the people who assign them; your own otherwise."""
    tasks = Task.objects.select_related("assigned_to", "assigned_by")
    if can_assign(user):
        return tasks
    return tasks.filter(assigned_to=user)


def short_date(day):
    """'Fri 30 Oct'."""
    return f"{day:%a} {day.day} {day:%b}"


@transaction.atomic
def assign(by, to, priority, description, due_date):
    if not can_assign(by):
        raise PermissionDenied("Only admins assign tasks.")
    if not to.is_active:
        raise TaskError(f"{to.display_name} no longer works here.")
    description = description.strip()
    if not description:
        raise TaskError("Describe the report or job.")
    if due_date < timezone.localdate():
        raise TaskError("The completion date can't be in the past.")

    task = Task.objects.create(
        assigned_to=to,
        assigned_by=by,
        priority=priority,
        description=description,
        due_date=due_date,
    )
    if to != by:
        due = short_date(due_date)
        post_notice(
            by, to, f"assigned you a task (P{priority}, due {due}): {task.title}"
        )
    return task


# Who may move a task to each status. The assignee works on it; an admin
# accepts the work by closing it, and may reopen it.
ASSIGNEE_STATUSES = {Status.OPEN, Status.ONGOING, Status.DONE}


def allowed_statuses(task, user):
    if can_assign(user):
        return list(Status)
    if task.assigned_to_id == user.pk and not task.is_closed:
        return [status for status in Status if status in ASSIGNEE_STATUSES]
    return []


@transaction.atomic
def set_status(task, user, status):
    task = (
        Task.objects.select_for_update(of=("self",))
        .select_related("assigned_to", "assigned_by")
        .get(pk=task.pk)
    )
    if status not in allowed_statuses(task, user):
        if task.assigned_to_id != user.pk:
            raise PermissionDenied("This isn't your task.")
        raise TaskError("Only an admin can close or reopen a task.")
    if status == task.status:
        return task

    task.status = status
    task.closed_at = timezone.now() if status == Status.CLOSED else None
    task.save()

    if status == Status.DONE and user.pk != task.assigned_by_id:
        post_notice(user, task.assigned_by, f"finished a task: {task.title}")
    elif status == Status.CLOSED and user.pk != task.assigned_to_id:
        post_notice(user, task.assigned_to, f"closed your task: {task.title}")
    return task
