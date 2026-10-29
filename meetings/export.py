from django.db.models import Q

from core.export import stamp, workbook_response

from .models import Conference, Slot, SlotRequest


def schedule_workbook(user, start=None, end=None):
    """Your booked time, blocked time, requests and conferences, with who answered what.

    Open office-hour slots nobody booked aren't part of anyone's schedule, so
    they are left out. A blocked slot is one the host cancelled with a reason;
    back-to-back slots blocked for the same reason are one row.
    """
    booked = Q(cancelled_at__isnull=True, booked_by__isnull=False)
    blocked = Q(host=user) & ~Q(block_reason="")
    slots = (
        Slot.objects.filter(Q(host=user) | Q(booked_by=user))
        .filter(booked | blocked)
        .select_related("host", "booked_by")
    )
    conferences = (
        Conference.objects.filter(Q(host=user) | Q(invitations__user=user))
        .select_related("host")
        .prefetch_related("invitations__user")
        .distinct()
    )
    if start:
        slots = slots.filter(starts_at__date__gte=start)
        conferences = conferences.filter(starts_at__date__gte=start)
    if end:
        slots = slots.filter(starts_at__date__lte=end)
        conferences = conferences.filter(starts_at__date__lte=end)

    meetings = []
    for s in slots.order_by("starts_at", "id"):
        if s.block_reason and s.cancelled_at:
            last = meetings[-1] if meetings else None
            if (
                last
                and last[2] == "Blocked time"
                and last[1] == s.starts_at
                and last[5] == s.block_reason
            ):
                meetings[-1] = (last[0], s.ends_at, *last[2:])
                continue
            meetings.append(
                (
                    s.starts_at,
                    s.ends_at,
                    "Blocked time",
                    s.host.display_name,
                    "",
                    s.block_reason,
                    None,
                )
            )
        else:
            meetings.append(
                (
                    s.starts_at,
                    s.ends_at,
                    "Time",
                    s.host.display_name,
                    s.booked_by.display_name,
                    s.topic,
                    s.booked_at,
                )
            )
    asks = SlotRequest.objects.filter(Q(slot__host=user) | Q(requester=user))
    if start:
        asks = asks.filter(slot__starts_at__date__gte=start)
    if end:
        asks = asks.filter(slot__starts_at__date__lte=end)
    request_rows = [
        (
            r.requester.display_name,
            r.slot.host.display_name,
            r.slot.starts_at,
            r.slot.ends_at,
            r.topic,
            r.get_status_display(),
            r.created_at,
            r.responded_at,
        )
        for r in asks.select_related("requester", "slot__host").order_by(
            "slot__starts_at", "id"
        )
    ]
    conference_rows, attendee_rows = [], []
    for c in conferences.order_by("starts_at", "id"):
        mine = next((i for i in c.invitations.all() if i.user_id == user.pk), None)
        conference_rows.append(
            (
                c.pk,
                c.title,
                c.starts_at,
                c.ends_at,
                c.location,
                c.host.display_name,
                c.agenda,
                "Cancelled" if c.is_cancelled else "On",
                "Host" if c.host_id == user.pk else mine.get_status_display(),
            )
        )
        attendee_rows.extend(
            (
                c.pk,
                c.title,
                c.starts_at,
                i.user.display_name,
                i.get_status_display(),
                i.responded_at,
            )
            for i in c.invitations.all()
        )
    return workbook_response(
        stamp("schedule"),
        {
            "Time slots": (
                ("From", "To", "Type", "Host", "Guest", "Topic or reason", "Booked"),
                meetings,
            ),
            "Requests": (
                (
                    "Asked by",
                    "Asked of",
                    "From",
                    "To",
                    "Topic",
                    "Status",
                    "Asked",
                    "Answered",
                ),
                request_rows,
            ),
            "Conferences": (
                (
                    "Conference #",
                    "Title",
                    "From",
                    "To",
                    "Where",
                    "Host",
                    "Agenda",
                    "Status",
                    "Your answer",
                ),
                conference_rows,
            ),
            "Attendees": (
                ("Conference #", "Title", "Starts", "Person", "Answer", "Answered"),
                attendee_rows,
            ),
        },
    )
