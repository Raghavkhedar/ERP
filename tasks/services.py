from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from chat.services import post_notice

from .models import Attachment, Status, Task, TaskUpdate


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
def assign(by, to, priority, description, due_date, files=()):
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
    attach(files, task=task)
    if to != by:
        due = short_date(due_date)
        post_notice(
            by, to, f"assigned you a task (P{priority}, due {due}): {task.title}"
        )
    return task


def attach(files, **owner):
    """Store uploads on a task or one of its updates (`task=` or `update=`)."""
    for upload in files:
        Attachment.objects.create(
            file=upload, original_name=upload.name, size=upload.size, **owner
        )


@transaction.atomic
def add_task_files(task, user, files):
    """Add files to a task after it was assigned."""
    if not can_assign(user):
        raise PermissionDenied("Only admins attach files to a task.")
    attach(files, task=task)


def allowed_statuses(task, user):
    """Only admins change a task's status; the assignee logs updates."""
    return list(Status) if can_assign(user) else []


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
        raise TaskError("Only an admin can change a task's status.")
    if status == task.status:
        return task

    task.status = status
    task.closed_at = timezone.now() if status == Status.CLOSED else None
    task.save()

    if user.pk != task.assigned_to_id:
        if status == Status.CLOSED:
            body = f"closed your task: {task.title}"
        else:
            body = f"marked your task {task.get_status_display()}: {task.title}"
        post_notice(user, task.assigned_to, body)
    return task


def can_update(task, user):
    """Admins until it's closed; the assignee until an admin marks it done."""
    if can_assign(user):
        return not task.is_closed
    return task.assigned_to_id == user.pk and not task.is_finished


def updatable_tasks(user):
    """Tasks the user can log work on: see can_update."""
    tasks = visible_tasks(user)
    if can_assign(user):
        return tasks.exclude(status=Status.CLOSED)
    return tasks.exclude(status__in=(Status.DONE, Status.CLOSED))


NUDGE_COOLDOWN = timedelta(hours=24)


def can_nudge(task, user):
    return (
        task.assigned_to_id == user.pk
        and task.status in (Status.OPEN, Status.ONGOING)
        and not nudged_recently(task)
    )


def nudged_recently(task):
    return (
        task.nudged_at is not None and timezone.now() - task.nudged_at < NUDGE_COOLDOWN
    )


@transaction.atomic
def nudge(task, user):
    """Ask whoever assigned the task to review it and mark it done or closed."""
    task = Task.objects.select_for_update(of=("self",)).get(pk=task.pk)
    if task.assigned_to_id != user.pk:
        raise PermissionDenied("This isn't your task.")
    if task.status not in (Status.OPEN, Status.ONGOING):
        raise TaskError("An admin has already reviewed this task.")
    if nudged_recently(task):
        raise TaskError("You already reminded the admins today.")

    assigner = task.assigned_by
    if assigner.is_active and can_assign(assigner):
        admins = [assigner]
    else:
        admins = [
            admin
            for admin in get_user_model().objects.filter(is_active=True)
            if admin.pk != user.pk and can_assign(admin)
        ]
    if not admins:
        raise TaskError("There is no admin to remind.")
    for admin in admins:
        post_notice(
            user, admin, f"asks you to review and close their task: {task.title}"
        )
    task.nudged_at = timezone.now()
    task.save(update_fields=["nudged_at"])
    return task


@transaction.atomic
def add_update(task, user, body, files=()):
    """Log what was done today, with any files. Starts an Open task."""
    task = Task.objects.select_for_update(of=("self",)).get(pk=task.pk)
    if task.assigned_to_id != user.pk and not can_assign(user):
        raise PermissionDenied("This isn't your task.")
    if task.is_closed or (task.is_finished and not can_assign(user)):
        raise TaskError("This task is closed.")
    body = body.strip()
    if not body:
        raise TaskError("Say what you did.")

    update = TaskUpdate.objects.create(task=task, author=user, body=body)
    attach(files, update=update)
    if task.status == Status.OPEN and task.assigned_to_id == user.pk:
        task.status = Status.ONGOING
        task.save()
    return update
