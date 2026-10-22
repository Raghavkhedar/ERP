from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from meetings.services import live_slots

UPCOMING_LIMIT = 5


def _greeting(now):
    hour = timezone.localtime(now).hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


@login_required
def home(request):
    now = timezone.now()
    user = request.user
    meetings = list(
        live_slots()
        .filter(ends_at__gt=now, booked_by__isnull=False)
        .filter(Q(host=user) | Q(booked_by=user))
        .select_related("host", "booked_by")[:UPCOMING_LIMIT]
    )
    today = timezone.localdate(now)
    for slot in meetings:
        slot.other = slot.booked_by if slot.host_id == user.id else slot.host
        slot.days_away = (timezone.localdate(slot.starts_at) - today).days
    context = {
        "greeting": _greeting(now),
        "today": today,
        "meetings": meetings,
    }
    return render(request, "home.html", context)
