from datetime import datetime, timedelta

from django.utils import timezone

from .models import Slot
from .services import accept_request, request_slot


def open_slots(host, day, start_time, end_time, minutes):
    """Free slots of the given length from start to end, for tests."""
    start = timezone.make_aware(datetime.combine(day, start_time))
    end = timezone.make_aware(datetime.combine(day, end_time))
    length = timedelta(minutes=minutes)
    slots = []
    while start + length <= end:
        slots.append(
            Slot.objects.create(host=host, starts_at=start, ends_at=start + length)
        )
        start += length
    return slots


def book(slot, user, topic):
    """Book a slot for the user the only way possible: they ask, the host accepts."""
    accept_request(request_slot(slot, user, topic), slot.host)
    slot.refresh_from_db()
    return slot
