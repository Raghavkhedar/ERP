from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from meetings.models import Invitation
from meetings.services import OFFICE_DAYS, live_conferences, live_slots
from tasks.models import Task

from .models import DailyPlan, PlanItem

TEXT_MAX = PlanItem._meta.get_field("text").max_length
ITEM_LIMIT = 30


class PlanError(Exception):
    """A plan that can't be saved; the message is shown to the user."""


def is_plan_day(date):
    return date.weekday() in OFFICE_DAYS


def plan_for(user, date):
    return DailyPlan.objects.filter(user=user, date=date).first()


def is_set(plan):
    """A plan counts once it has at least one goal."""
    return plan is not None and plan.items.filter(kind=PlanItem.Kind.GOAL).exists()


def has_plan_today(user):
    return is_set(plan_for(user, timezone.localdate()))


def progress(plan):
    items = list(plan.items.all()) if plan else []
    return sum(i.done for i in items), len(items)


def save_plan(user, date, rows):
    """Save the day's plan from rows of (id, kind, text, done, starts_at, ends_at).

    The rows are the whole plan: a row with an id keeps that item, a row without
    one is new, and items left out are removed. Work needs a time slot, and
    slots can't overlap; goals have none.
    """
    cleaned = []
    for item_id, kind, text, done, start, end in rows:
        text = text.strip()
        if not text:
            continue
        if kind not in PlanItem.Kind.values:
            raise PlanError("Something in the plan wasn't right. Please try again.")
        if len(text) > TEXT_MAX:
            raise PlanError(f"Keep each line under {TEXT_MAX} characters.")
        if kind == PlanItem.Kind.GOAL:
            start = end = None
        elif start is None or end is None:
            raise PlanError(
                f"Give \u201c{text}\u201d a start and end time, like 09:30."
            )
        elif end <= start:
            raise PlanError(f"\u201c{text}\u201d should end after it starts.")
        cleaned.append((item_id, kind, text, done, start, end))
    if len(cleaned) > ITEM_LIMIT:
        raise PlanError(f"A day's plan can hold up to {ITEM_LIMIT} lines.")
    if not any(row[1] == PlanItem.Kind.GOAL for row in cleaned):
        raise PlanError("Add at least one goal for the day.")
    timed = sorted((r for r in cleaned if r[4]), key=lambda r: r[4])
    for first, second in zip(timed, timed[1:], strict=False):
        if second[4] < first[5]:
            raise PlanError(
                f"\u201c{first[2]}\u201d and \u201c{second[2]}\u201d overlap. "
                "Move one of them."
            )

    with transaction.atomic():
        plan, _ = DailyPlan.objects.select_for_update().get_or_create(
            user=user, date=date
        )
        existing = {item.pk: item for item in plan.items.all()}
        kept = set()
        for position, (item_id, kind, text, done, start, end) in enumerate(cleaned):
            values = dict(
                kind=kind,
                text=text,
                done=done,
                starts_at=start,
                ends_at=end,
                position=position,
            )
            item = existing.get(item_id)
            if item is None:
                PlanItem.objects.create(plan=plan, **values)
                continue
            kept.add(item.pk)
            if any(getattr(item, k) != v for k, v in values.items()):
                for k, v in values.items():
                    setattr(item, k, v)
                item.save()
        for pk, item in existing.items():
            if pk not in kept:
                item.delete()
        plan.save()  # bump updated_at
    return plan


def agenda(user, date):
    """The user's booked meetings and conferences on the day, as (start, end, title)."""
    start = timezone.make_aware(datetime.combine(date, time.min))
    end = timezone.make_aware(datetime.combine(date + timedelta(days=1), time.min))
    entries = []
    slots = (
        live_slots()
        .filter(booked_by__isnull=False, starts_at__gte=start, starts_at__lt=end)
        .filter(Q(host=user) | Q(booked_by=user))
        .select_related("host", "booked_by")
    )
    for slot in slots:
        other = slot.booked_by if slot.host_id == user.id else slot.host
        title = f"Meeting with {other.display_name}"
        entries.append((slot.starts_at, slot.ends_at, title))
    conferences = (
        live_conferences()
        .filter(starts_at__gte=start, starts_at__lt=end)
        .filter(
            Q(host=user)
            | Q(
                invitations__user=user,
                invitations__status__in=[
                    Invitation.Status.INVITED,
                    Invitation.Status.ACCEPTED,
                ],
            )
        )
        .distinct()
    )
    for conference in conferences:
        entries.append((conference.starts_at, conference.ends_at, conference.title))
    return sorted(entries)


def can_view(viewer, owner):
    """The owner, superusers, and people who have assigned the owner a task."""
    if viewer.pk == owner.pk or viewer.is_superuser:
        return True
    return Task.objects.filter(assigned_by=viewer, assigned_to=owner).exists()


PANEL_HOUR_HEIGHT = 40  # pixels per hour in the home page's day panel
PANEL_START, PANEL_END = 9, 18  # hours always shown


def day_panel(user, date):
    """Everything the home page's "Your day" panel draws: goals and a timeline.

    Work items and meetings are blocks placed by time; `now_top` is the pixel
    offset of the current time when `date` is today.
    """
    plan = plan_for(user, date)
    items = list(plan.items.all()) if plan else []
    blocks = []
    for item in items:
        if item.kind == PlanItem.Kind.WORK and item.starts_at:
            blocks.append(
                {
                    "start": item.starts_at,
                    "end": item.ends_at,
                    "title": item.text,
                    "done": item.done,
                    "meeting": False,
                }
            )
    for start, end, title in agenda(user, date):
        blocks.append(
            {
                "start": timezone.localtime(start).time(),
                "end": timezone.localtime(end).time()
                if timezone.localtime(end).date() == date
                else time.max,
                "title": title,
                "done": False,
                "meeting": True,
            }
        )
    blocks.sort(key=lambda b: b["start"])
    first = min([PANEL_START] + [b["start"].hour for b in blocks])
    last = max(
        [PANEL_END]
        + [
            b["end"].hour + (1 if b["end"].minute or b["end"] == time.max else 0)
            for b in blocks
        ]
    )
    last = min(last, 24)

    def offset(moment):
        return round(
            ((moment.hour - first) * 60 + moment.minute) * PANEL_HOUR_HEIGHT / 60
        )

    for block in blocks:
        block["top"] = offset(block["start"])
        bottom = (
            (last - first) * PANEL_HOUR_HEIGHT
            if block["end"] == time.max
            else offset(block["end"])
        )
        block["height"] = max(bottom - block["top"], 20)
    now = timezone.localtime()
    now_top = None
    if now.date() == date and first <= now.hour < last:
        now_top = offset(now.time())
    done, total = progress(plan)
    return {
        "goals": [i for i in items if i.kind == PlanItem.Kind.GOAL],
        "blocks": blocks,
        "hours": [
            (time(h), (h - first) * PANEL_HOUR_HEIGHT) for h in range(first, last)
        ],
        "height": (last - first) * PANEL_HOUR_HEIGHT,
        "now_top": now_top,
        "done": done,
        "total": total,
    }
