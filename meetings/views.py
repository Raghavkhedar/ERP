import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import BookingForm
from .models import Slot
from .services import (
    SlotError,
    block,
    book,
    cancel,
    live_slots,
    open_upcoming_office_hours,
    unblock,
)


def _with_days(slots):
    """The slots, each with its local date for grouping in templates."""
    slots = list(slots)
    for slot in slots:
        slot.day = timezone.localdate(slot.starts_at)
    return slots


HOUR_HEIGHT = 64  # pixels per hour in the day view
DAY_START, DAY_END = 8, 19  # hours always shown in the day view


def _day_url(day):
    return reverse("meetings:day", args=[day.year, day.month, day.day])


def _midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _my_slots(user, first_day, last_day):
    """The user's meetings (either side) and own free slots on these days.

    Free slots that have already ended are left out: nobody can book them.
    """
    slots = (
        live_slots()
        .filter(Q(host=user) | Q(booked_by=user))
        .exclude(booked_by__isnull=True, ends_at__lte=timezone.now())
        .filter(
            starts_at__gte=_midnight(first_day),
            starts_at__lt=_midnight(last_day + timedelta(days=1)),
        )
        .select_related("host", "booked_by")
    )
    slots = list(slots)
    for slot in slots:
        slot.day = timezone.localdate(slot.starts_at)
        if slot.is_booked:
            slot.other = slot.booked_by if slot.host_id == user.pk else slot.host
    return slots


@login_required
def schedule(request, year=None, month=None):
    """The month calendar; the current month when none is given."""
    open_upcoming_office_hours()
    today = timezone.localdate()
    if year is None:
        year, month = today.year, today.month
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise Http404("No such month.")
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)

    by_day = defaultdict(list)
    for slot in _my_slots(request.user, weeks[0][0], weeks[-1][-1]):
        by_day[slot.day].append(slot)
    weeks = [
        [
            {
                "date": day,
                "in_month": day.month == month,
                "is_today": day == today,
                "meetings": [s for s in by_day[day] if s.is_booked],
                "free": sum(1 for s in by_day[day] if not s.is_booked),
            }
            for day in week
        ]
        for week in weeks
    ]
    first = date(year, month, 1)
    previous = first - timedelta(days=1)
    following = first + timedelta(days=32)
    context = {
        "month": first,
        "weeks": weeks,
        "weekdays": list(calendar.day_abbr),
        "previous": (previous.year, previous.month),
        "following": (following.year, following.month),
        "today": today,
    }
    return render(request, "meetings/month.html", context)


@dataclass
class OpenHours:
    """A run of back-to-back free office-hours slots, shown as one block."""

    starts_at: datetime
    ends_at: datetime
    free: int = 1
    is_booked = False
    is_open_hours = True

    @property
    def anchor(self):
        return f"hours-{timezone.localtime(self.starts_at):%H%M}"


def _merge_open_hours(slots):
    """Each free office-hours run becomes one OpenHours; other slots stay."""
    merged = []
    for slot in slots:
        if not slot.office_hours or slot.is_booked:
            slot.anchor = f"slot-{slot.pk}"
            merged.append(slot)
        elif (
            merged
            and isinstance(merged[-1], OpenHours)
            and merged[-1].ends_at == slot.starts_at
        ):
            merged[-1].ends_at = slot.ends_at
            merged[-1].free += 1
        else:
            merged.append(OpenHours(slot.starts_at, slot.ends_at))
    return merged


@login_required
def day_view(request, year, month, day):
    open_upcoming_office_hours()
    try:
        shown = date(year, month, day)
    except ValueError:
        raise Http404("No such day.") from None
    slots = _merge_open_hours(_my_slots(request.user, shown, shown))

    first_hour, last_hour = DAY_START, DAY_END
    for slot in slots:
        start = timezone.localtime(slot.starts_at)
        end = timezone.localtime(slot.ends_at)
        first_hour = min(first_hour, start.hour)
        ends_on_hour = end.minute == 0 and end.date() == shown
        last_hour = max(last_hour, end.hour if ends_on_hour else min(end.hour + 1, 24))
    for slot in slots:
        start = timezone.localtime(slot.starts_at)
        minutes = (start.hour - first_hour) * 60 + start.minute
        length = (slot.ends_at - slot.starts_at).total_seconds() / 60
        slot.top = round(minutes * HOUR_HEIGHT / 60)
        slot.height = max(round(length * HOUR_HEIGHT / 60), 18)

    today = timezone.localdate()
    context = {
        "day": shown,
        "today": today,
        "is_today": shown == today,
        "slots": slots,
        "now": timezone.now(),
        "hours": [
            (time(hour), (hour - first_hour) * HOUR_HEIGHT)
            for hour in range(first_hour, last_hour)
        ],
        "timeline_height": (last_hour - first_hour) * HOUR_HEIGHT,
        "previous": shown - timedelta(days=1),
        "following": shown + timedelta(days=1),
        "now_top": _now_top(shown, first_hour, last_hour),
    }
    return render(request, "meetings/day.html", context)


def _now_top(shown, first_hour, last_hour):
    """Where the 'now' line goes on today's timeline, or None."""
    now = timezone.localtime()
    if now.date() != shown or not first_hour <= now.hour < last_hour:
        return None
    return round(((now.hour - first_hour) * 60 + now.minute) * HOUR_HEIGHT / 60)


def _block_url(day):
    return reverse("meetings:block_day", args=[day.year, day.month, day.day])


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _block_or_unblock(request, shown):
    """Apply the button pressed on the block-time page, and say what happened."""
    action = request.POST.get("action")
    pks = request.POST.getlist("slot")
    if action == "block_day":
        day_slots = Slot.objects.filter(
            host=request.user,
            starts_at__gte=_midnight(shown),
            starts_at__lt=_midnight(shown + timedelta(days=1)),
        )
        pks = list(day_slots.values_list("pk", flat=True))
    if action in ("block", "block_day"):
        # One reason per stretch of back-to-back slots; a whole day has one.
        free = list(
            Slot.objects.filter(
                pk__in=pks,
                host=request.user,
                cancelled_at__isnull=True,
                booked_by__isnull=True,
                starts_at__gt=timezone.now(),
            )
        )
        if not free:
            messages.error(request, "There were no free slots to block.")
            return
        if action == "block_day":
            stretches = [(free, request.POST.get("reason_day", ""))]
        else:
            stretches = [
                (run, request.POST.get(f"reason_{run[0].pk}", ""))
                for run in _runs(free)
            ]
        if not all(reason.strip() for _, reason in stretches):
            messages.error(request, "Say why you're blocking each stretch of time.")
            return
        try:
            blocked = sum(
                block(request.user, [s.pk for s in run], reason)
                for run, reason in stretches
            )
        except SlotError as error:
            messages.error(request, str(error))
            return
        messages.success(request, f"Blocked {_plural(blocked, 'slot')}.")
    elif action == "unblock":
        opened = unblock(request.user, pks)
        if opened:
            messages.success(
                request,
                f"Unblocked {_plural(opened, 'slot')}. Others can book them again.",
            )
        kept = len(pks) - opened
        if kept:
            messages.error(
                request,
                f"{_plural(kept, 'slot')} stayed blocked: you have a meeting then, "
                "or the time has passed.",
            )


def _runs(slots):
    """Split the slots into runs of back-to-back times (before and after lunch)."""
    runs = []
    for slot in slots:
        if runs and runs[-1][-1].ends_at == slot.starts_at:
            runs[-1].append(slot)
        else:
            runs.append([slot])
    return runs


@login_required
def block_time(request, year=None, month=None, day=None):
    """The user's slots for one day, to block or unblock times."""
    open_upcoming_office_hours()
    today = timezone.localdate()
    try:
        shown = today if year is None else date(year, month, day)
    except ValueError:
        raise Http404("No such day.") from None
    if request.method == "POST":
        _block_or_unblock(request, shown)
        return redirect(_block_url(shown))

    in_day = {
        "starts_at__gte": _midnight(shown),
        "starts_at__lt": _midnight(shown + timedelta(days=1)),
    }
    # Office hours plus any slots opened by hand before office hours existed.
    # A removed slot whose time is in use by another slot isn't shown twice.
    slots = list(
        Slot.objects.filter(host=request.user, **in_day).select_related("booked_by")
    )
    live = [s for s in slots if not s.is_cancelled]
    slots = [
        slot
        for slot in slots
        if not slot.is_cancelled
        or not any(
            s.starts_at < slot.ends_at and s.ends_at > slot.starts_at for s in live
        )
    ]
    as_guest = list(
        live_slots().filter(booked_by=request.user, **in_day).select_related("host")
    )
    now = timezone.now()
    for slot in slots:
        if slot.is_cancelled:
            slot.state = "blocked"
        elif slot.is_booked:
            slot.state = "booked"
        else:
            slot.state = "free"
        slot.started = slot.starts_at <= now
        slot.meeting = next(
            (
                m
                for m in as_guest
                if m.starts_at < slot.ends_at and m.ends_at > slot.starts_at
            ),
            None,
        )
    context = {
        "day": shown,
        "today": today,
        "is_sunday": shown.weekday() == 6,
        "runs": _runs(slots),
        "can_block": any(s.state == "free" and not s.started for s in slots),
        "previous": shown - timedelta(days=1),
        "following": shown + timedelta(days=1),
    }
    return render(request, "meetings/block.html", context)


@login_required
def people(request):
    open_upcoming_office_hours()
    free = Q(
        hosted_slots__booked_by__isnull=True,
        hosted_slots__cancelled_at__isnull=True,
        hosted_slots__starts_at__gt=timezone.now(),
    )
    people = (
        get_user_model()
        .objects.filter(is_active=True)
        .exclude(pk=request.user.pk)
        .annotate(free_slots=Count("hosted_slots", filter=free))
        .order_by("first_name", "last_name", "username")
    )
    return render(request, "meetings/people.html", {"people": people})


@login_required
def person_slots(request, user_id):
    open_upcoming_office_hours()
    person = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    if person == request.user:
        return redirect("meetings:schedule")
    slots = live_slots().filter(
        host=person, booked_by__isnull=True, starts_at__gt=timezone.now()
    )
    context = {"person": person, "slots": _with_days(slots)}
    return render(request, "meetings/person_slots.html", context)


@login_required
def book_slot(request, pk):
    slot = get_object_or_404(
        live_slots().select_related("host"), pk=pk, booked_by__isnull=True
    )
    form = BookingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            book(slot, request.user, form.cleaned_data["topic"])
        except SlotError as error:
            form.add_error(None, str(error))
        else:
            return redirect(_day_url(timezone.localdate(slot.starts_at)))
    return render(request, "meetings/book.html", {"slot": slot, "form": form})


@login_required
@require_POST
def cancel_slot(request, pk):
    slot = get_object_or_404(Slot, pk=pk)
    was_host = slot.host_id == request.user.pk
    was_booked = slot.is_booked
    try:
        cancel(slot, request.user)
    except SlotError as error:
        messages.error(request, str(error))
    else:
        if not was_host:
            messages.success(request, "Booking cancelled. The slot is free again.")
        elif was_booked:
            messages.success(request, "Meeting cancelled and the slot removed.")
        else:
            messages.success(request, "Slot removed.")
    return redirect(_day_url(timezone.localdate(slot.starts_at)))
