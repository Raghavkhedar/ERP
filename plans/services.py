from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from meetings.models import Invitation
from meetings.services import OFFICE_DAYS, live_conferences, live_slots

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
    """Save the day's plan from rows of (id, kind, text, done).

    The rows are the whole plan: a row with an id keeps that item, a row without
    one is new, and items left out are removed.
    """
    cleaned = []
    for item_id, kind, text, done in rows:
        text = text.strip()
        if not text:
            continue
        if kind not in PlanItem.Kind.values:
            raise PlanError("Something in the plan wasn't right. Please try again.")
        if len(text) > TEXT_MAX:
            raise PlanError(f"Keep each line under {TEXT_MAX} characters.")
        cleaned.append((item_id, kind, text, done))
    if len(cleaned) > ITEM_LIMIT:
        raise PlanError(f"A day's plan can hold up to {ITEM_LIMIT} lines.")
    if not any(kind == PlanItem.Kind.GOAL for _, kind, _, _ in cleaned):
        raise PlanError("Add at least one goal for the day.")

    with transaction.atomic():
        plan, _ = DailyPlan.objects.select_for_update().get_or_create(
            user=user, date=date
        )
        existing = {item.pk: item for item in plan.items.all()}
        kept = set()
        for position, (item_id, kind, text, done) in enumerate(cleaned):
            item = existing.get(item_id)
            if item is None:
                PlanItem.objects.create(
                    plan=plan, kind=kind, text=text, done=done, position=position
                )
                continue
            kept.add(item.pk)
            if (item.kind, item.text, item.done, item.position) != (
                kind,
                text,
                done,
                position,
            ):
                item.kind, item.text, item.done, item.position = (
                    kind,
                    text,
                    done,
                    position,
                )
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
