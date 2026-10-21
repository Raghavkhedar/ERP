from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import OpenSlotsForm
from .services import SlotError, live_slots, open_slots


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
