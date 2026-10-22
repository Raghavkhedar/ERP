from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import BookingForm, OpenSlotsForm
from .models import Slot
from .services import SlotError, book, cancel, live_slots, open_slots


def _upcoming():
    return live_slots().filter(ends_at__gt=timezone.now())


def _with_days(slots):
    """The slots, each with its local date for grouping in templates."""
    slots = list(slots)
    for slot in slots:
        slot.day = timezone.localdate(slot.starts_at)
    return slots


@login_required
def schedule(request):
    mine = _upcoming().filter(host=request.user)
    context = {
        "booked_with_me": _with_days(
            mine.filter(booked_by__isnull=False).select_related("booked_by")
        ),
        "my_bookings": _with_days(
            _upcoming().filter(booked_by=request.user).select_related("host")
        ),
        "open_slots": _with_days(mine.filter(booked_by__isnull=True)),
    }
    return render(request, "meetings/schedule.html", context)


@login_required
def open_slots_view(request):
    form = OpenSlotsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            data = form.cleaned_data
            open_slots(
                request.user, data["date"], data["start"], data["end"], data["minutes"]
            )
        except SlotError as error:
            form.add_error(None, str(error))
        else:
            return redirect("meetings:schedule")
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
            return redirect("meetings:schedule")
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
    return redirect("meetings:schedule")
