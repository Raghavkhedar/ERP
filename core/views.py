from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from meetings.models import Invitation
from meetings.services import live_conferences, live_slots
from tasks.views import timeline_context

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
    for slot in meetings:
        other = slot.booked_by if slot.host_id == user.id else slot.host
        slot.other = other
        slot.title, slot.subtitle, slot.avatar = other.display_name, slot.topic, other
    conferences = list(
        live_conferences()
        .filter(ends_at__gt=now)
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
        .select_related("host")
        .distinct()[:UPCOMING_LIMIT]
    )
    for conference in conferences:
        conference.avatar = conference.host
        conference.subtitle = (
            "Conference · you're hosting"
            if conference.host_id == user.id
            else f"Conference · {conference.host.display_name}"
        )
    meetings = sorted(meetings + conferences, key=lambda e: e.starts_at)[
        :UPCOMING_LIMIT
    ]
    today = timezone.localdate(now)
    for entry in meetings:
        entry.days_away = (timezone.localdate(entry.starts_at) - today).days
    context = {
        "greeting": _greeting(now),
        "today": today,
        "meetings": meetings,
        **timeline_context(request),
    }
    return render(request, "home.html", context)
