from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from chat.services import post_notice

from .models import Attachment, DateChange, Repeat, Status, Task, TaskUpdate


class TaskError(Exception):
    """A request that breaks a task rule; the message is shown to the user."""


def is_supervisor(user):
    return user.reports.filter(is_active=True).exists()


def can_assign(user):
    """Admins, and supervisors for the people they supervise."""
    return user.is_office_admin or is_supervisor(user)


def manages(user, task):
    """Admins manage every task; a supervisor, their reports' tasks."""
    return user.is_office_admin or task.assigned_to.supervisor_id == user.pk


def assignable_people(user):
    """Who `user` can give a task to: everyone for an admin, otherwise
    themselves and the people they supervise.
    """
    people = get_user_model().objects.filter(is_active=True)
    if not user.is_office_admin:
        people = people.filter(Q(pk=user.pk) | Q(supervisor=user))
    return people.order_by("first_name", "last_name", "username")


def visible_tasks(user):
    """Everyone's tasks for admins; a supervisor's reports' and their own;
    your own otherwise.
    """
    tasks = Task.objects.select_related("assigned_to", "assigned_by")
    if user.is_office_admin:
        return tasks
    if is_supervisor(user):
        return tasks.filter(Q(assigned_to=user) | Q(assigned_to__supervisor=user))
    return tasks.filter(assigned_to=user)


def short_date(day):
    """'Fri 30 Oct'."""
    return f"{day:%a} {day.day} {day:%b}"


def is_personal(task):
    """A task someone gave themselves."""
    return task.assigned_to_id == task.assigned_by_id


@transaction.atomic
def assign(
    by, to, priority, description, due_date, files=(), remind_at=None, remind_every=""
):
    if to != by and not (by.is_office_admin or to.supervisor_id == by.pk):
        raise PermissionDenied(
            "Only admins and supervisors assign tasks to other people."
        )
    if not to.is_active:
        raise TaskError(f"{to.display_name} no longer works here.")
    description = description.strip()
    if not description:
        raise TaskError("Describe the report or job.")
    if due_date < timezone.localdate():
        raise TaskError("The completion date can't be in the past.")
    if remind_at and remind_at <= timezone.now():
        raise TaskError("Set the alarm for a time that hasn't passed.")

    task = Task.objects.create(
        assigned_to=to,
        assigned_by=by,
        priority=priority,
        description=description,
        due_date=due_date,
        remind_at=remind_at,
        remind_every=remind_every if remind_at else "",
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
    if not manages(user, task):
        raise PermissionDenied("Only admins and supervisors attach files to a task.")
    attach(files, task=task)


def allowed_statuses(task, user):
    """Admins and the assignee's supervisor change a task's status, and so does
    whoever gave it to themselves; other assignees log updates.
    """
    if manages(user, task) or (is_personal(task) and task.assigned_to_id == user.pk):
        return list(Status)
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


def can_reschedule(task, user):
    """Admins and the assignee's supervisor move the date until it's closed."""
    return manages(user, task) and not task.is_closed


@transaction.atomic
def reschedule(task, user, due_date, reason):
    """Move the completion date earlier or later, keeping who and why."""
    task = (
        Task.objects.select_for_update(of=("self",))
        .select_related("assigned_to", "assigned_by")
        .get(pk=task.pk)
    )
    if not can_reschedule(task, user):
        raise PermissionDenied("Only admins and supervisors change the date.")
    reason = reason.strip()
    if not reason:
        raise TaskError("Give a reason for the change.")
    if due_date == task.due_date:
        raise TaskError("That is already the completion date.")
    if due_date < timezone.localdate(task.received_at):
        raise TaskError("The completion date can't be before the task was received.")

    change = DateChange.objects.create(
        task=task,
        changed_by=user,
        old_date=task.due_date,
        new_date=due_date,
        reason=reason,
    )
    task.due_date = due_date
    task.save()
    if user.pk != task.assigned_to_id:
        post_notice(
            user,
            task.assigned_to,
            f"moved the completion date from {short_date(change.old_date)} "
            f"to {short_date(due_date)} ({reason}): {task.title}",
        )
    return change


def can_update(task, user):
    """Admins and supervisors until it's closed; the assignee until it's marked done."""
    if manages(user, task):
        return not task.is_closed
    return task.assigned_to_id == user.pk and not task.is_finished


def updatable_tasks(user):
    """Tasks the user can log work on: see can_update."""
    tasks = visible_tasks(user).exclude(status=Status.CLOSED)
    if user.is_office_admin:
        return tasks
    return tasks.exclude(Q(status=Status.DONE) & ~Q(assigned_to__supervisor=user))


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
    if assigner.is_active and manages(assigner, task):
        admins = [assigner]
    else:
        admins = [
            admin
            for admin in get_user_model().objects.filter(is_active=True)
            if admin.pk != user.pk
            and (admin.is_office_admin or admin.pk == task.assigned_to.supervisor_id)
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
    if task.assigned_to_id != user.pk and not manages(user, task):
        raise PermissionDenied("This isn't your task.")
    if task.is_closed or (task.is_finished and not manages(user, task)):
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


SNOOZES = {"10m": timedelta(minutes=10), "1h": timedelta(hours=1)}
REPEAT_STEP = {Repeat.DAILY: timedelta(days=1), Repeat.WEEKLY: timedelta(weeks=1)}


def can_set_alarm(task, user):
    """The assignee, or an admin or supervisor setting one for them, until the
    task is finished.
    """
    return not task.is_finished and (
        task.assigned_to_id == user.pk or manages(user, task)
    )


def due_alarms(user):
    """Alarms ringing now: the user's unfinished tasks whose time has come."""
    return Task.objects.filter(
        assigned_to=user,
        status__in=(Status.OPEN, Status.ONGOING),
        remind_at__lte=timezone.now(),
    ).order_by("remind_at")


def next_alarm_in(user):
    """Seconds until the user's next alarm rings, or None if none is waiting."""
    upcoming = (
        Task.objects.filter(
            assigned_to=user,
            status__in=(Status.OPEN, Status.ONGOING),
            remind_at__gt=timezone.now(),
        )
        .order_by("remind_at")
        .values_list("remind_at", flat=True)
        .first()
    )
    if upcoming is None:
        return None
    return max((upcoming - timezone.now()).total_seconds(), 0)


def _own_alarm(task, user):
    task = Task.objects.select_for_update(of=("self",)).get(pk=task.pk)
    if not can_set_alarm(task, user):
        raise PermissionDenied("You can't set an alarm on this task.")
    return task


@transaction.atomic
def set_alarm(task, user, remind_at, every=""):
    """Ring at `remind_at`, and again every day or week if `every` says so;
    no time clears the alarm.
    """
    task = _own_alarm(task, user)
    if remind_at and remind_at <= timezone.now():
        raise TaskError("Set the alarm for a time that hasn't passed.")
    task.remind_at = remind_at
    task.remind_every = every if remind_at else ""
    task.save(update_fields=["remind_at", "remind_every"])
    return task


@transaction.atomic
def snooze_alarm(task, user, length):
    task = _own_alarm(task, user)
    now = timezone.now()
    if length == "tomorrow":
        morning = timezone.localtime(now).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        task.remind_at = morning + timedelta(days=1)
    elif length in SNOOZES:
        task.remind_at = now + SNOOZES[length]
    else:
        raise TaskError("Choose how long to snooze.")
    task.save(update_fields=["remind_at"])
    return task


@transaction.atomic
def dismiss_alarm(task, user):
    """Stop this ring: a repeating alarm moves to its next time, a one-off ends."""
    task = _own_alarm(task, user)
    now = timezone.now()
    if task.remind_at is None or task.remind_at > now:
        return task  # already stopped or snoozed from another tab
    step = REPEAT_STEP.get(task.remind_every)
    if step:
        while task.remind_at <= now:
            task.remind_at += step
    else:
        task.remind_at = None
    task.save(update_fields=["remind_at"])
    return task
