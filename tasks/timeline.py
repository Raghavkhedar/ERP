"""The home page's Tasks timeline: each task as a bar across a window of days."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import groupby

from django.db.models import Q
from django.utils import timezone

from .models import Status, TaskUpdate
from .services import can_assign, visible_tasks

DAYS = 14
DAYS_BEFORE_TODAY = 4
SUNDAY = 6  # not an office day: a narrower column


@dataclass
class Bar:
    task: object
    start: int  # grid column lines, counting the label column as line 1
    end: int
    overdue_from: int | None  # where the red overdue part starts, if any
    clipped_left: bool
    clipped_right: bool
    shows_due: bool  # the completion date falls inside the window
    updates: list = field(default_factory=list)  # Dots, one per day with updates

    @property
    def main_end(self):
        """Where the bar's normal part stops: at the overdue part, if any."""
        return self.overdue_from or self.end

    @property
    def has_main(self):
        return self.main_end > self.start


@dataclass
class Dot:
    column: int
    update: object  # the day's latest update
    count: int


@dataclass
class Group:
    person: object  # None when the viewer sees only their own tasks
    bars: list = field(default_factory=list)


@dataclass
class Timeline:
    start: date
    days: list
    groups: list
    today: date
    grid_columns: str

    @property
    def end(self):
        return self.days[-1]

    @property
    def previous(self):
        return self.start - timedelta(days=7)

    @property
    def following(self):
        return self.start + timedelta(days=7)

    @property
    def default_start(self):
        return self.today - timedelta(days=DAYS_BEFORE_TODAY)

    @property
    def is_default(self):
        return self.start == self.default_start

    @property
    def today_column(self):
        if self.start <= self.today <= self.end:
            return (self.today - self.start).days + 2
        return None

    @property
    def is_empty(self):
        return not any(group.bars for group in self.groups)


def parse_start(value, today):
    """The first day from ?from=YYYY-MM-DD, or a few days before today."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return today - timedelta(days=DAYS_BEFORE_TODAY)


def _column(day, start):
    return (day - start).days + 2


def _bar(task, start, end, today):
    received = timezone.localdate(task.received_at)
    finish = task.due_date
    overdue = task.is_overdue
    if overdue:
        finish = today
    if received > end or finish < start:
        return None
    first, last = max(received, start), min(finish, end)
    overdue_from = None
    if overdue and task.due_date < last:
        overdue_from = _column(max(task.due_date + timedelta(days=1), start), start)
    return Bar(
        task=task,
        start=_column(first, start),
        end=_column(last, start) + 1,
        overdue_from=overdue_from,
        clipped_left=received < start,
        clipped_right=finish > end,
        shows_due=start <= task.due_date <= end,
    )


def build(user, start=None, person=None):
    """The timeline for the user; an assigner may narrow it to one person."""
    today = timezone.localdate()
    start = start or today - timedelta(days=DAYS_BEFORE_TODAY)
    days = [start + timedelta(days=n) for n in range(DAYS)]
    end = days[-1]

    window_start = timezone.make_aware(datetime.combine(start, time.min))
    window_end = timezone.make_aware(datetime.combine(end + timedelta(1), time.min))
    tasks = (
        visible_tasks(user)
        .filter(received_at__lt=window_end)
        .filter(~Q(status=Status.CLOSED) | Q(closed_at__gte=window_start))
    )
    if person is not None:
        tasks = tasks.filter(assigned_to=person)

    assigner = can_assign(user)
    if assigner:
        tasks = tasks.order_by(
            "assigned_to__first_name",
            "assigned_to__last_name",
            "assigned_to",
            *tasks.model._meta.ordering,
        )
        people = groupby(tasks, key=lambda task: task.assigned_to)
    else:
        people = [(None, tasks)]

    by_task_day = {}
    updates = TaskUpdate.objects.filter(
        task__in=tasks, created_at__gte=window_start, created_at__lt=window_end
    ).order_by("created_at", "id")
    for update in updates:
        day = timezone.localdate(update.created_at)
        dots = by_task_day.setdefault(update.task_id, {})
        if day in dots:
            dots[day].update = update
            dots[day].count += 1
        else:
            dots[day] = Dot(column=_column(day, start), update=update, count=1)

    groups = []
    for person, person_tasks in people:
        bars = [bar for task in person_tasks if (bar := _bar(task, start, end, today))]
        for bar in bars:
            bar.updates = list(by_task_day.get(bar.task.pk, {}).values())
        if bars:
            groups.append(Group(person=person, bars=bars))

    columns = [
        "minmax(1.75rem,0.5fr)" if d.weekday() == SUNDAY else "minmax(2.75rem,1fr)"
        for d in days
    ]
    return Timeline(
        start=start,
        days=days,
        groups=groups,
        today=today,
        grid_columns="var(--label) " + " ".join(columns),
    )
