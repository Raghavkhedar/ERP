import calendar
from collections import defaultdict
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

from .forms import BookingForm, OpenSlotsForm
from .models import Slot
from .services import SlotError, book, cancel, live_slots, open_slots


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


@login_required
def day_view(request, year, month, day):
    try:
        shown = date(year, month, day)
    except ValueError:
        raise Http404("No such day.") from None
    slots = _my_slots(request.user, shown, shown)

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


def _date_from(query):
    """{'date': ...} from ?date=YYYY-MM-DD, so a day's page can prefill the form."""
    try:
        return {"date": date.fromisoformat(query.get("date", ""))}
    except ValueError:
        return {}


@login_required
def open_slots_view(request):
    form = OpenSlotsForm(request.POST or None, initial=_date_from(request.GET))
    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data
            open_slots(
                request.user, data["date"], data["start"], data["end"], data["minutes"]
            )
        except SlotError as error:
            form.add_error(None, str(error))
        else:
            return redirect(_day_url(data["date"]))
    return render(request, "meetings/open_slots.html", {"form": form})


@login_required
def people(request):
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
