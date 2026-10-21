from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Slot

SLOT_LENGTHS = [15, 30, 45, 60]


class SlotError(Exception):
    """A request that breaks a scheduling rule; the message is shown to the user."""


def live_slots():
    return Slot.objects.filter(cancelled_at__isnull=True)


def overlapping(slots, start, end):
    return slots.filter(starts_at__lt=end, ends_at__gt=start)


def is_busy(user, start, end):
    """Whether the user has a booked meeting, as host or guest, in this time."""
    booked = live_slots().filter(booked_by__isnull=False)
    mine = booked.filter(Q(host=user) | Q(booked_by=user))
    return overlapping(mine, start, end).exists()


def local_time(moment):
    return timezone.localtime(moment).strftime("%H:%M")


def _lock(*users):
    """Lock the users' rows, in a fixed order, until the transaction ends."""
    pks = sorted(user.pk for user in users)
    list(get_user_model().objects.select_for_update().filter(pk__in=pks).order_by("pk"))


@transaction.atomic
def open_slots(host, date, start_time, end_time, minutes):
    """Split the time range into slots of the given length. All or nothing."""
    start = timezone.make_aware(datetime.combine(date, start_time))
    end = timezone.make_aware(datetime.combine(date, end_time))
    length = timedelta(minutes=minutes)
    if end <= start:
        raise SlotError("The end time must be after the start time.")
    if start < timezone.now():
        raise SlotError("Slots can't start in the past.")
    if end - start < length:
        raise SlotError(f"The time range is shorter than one {minutes}-minute slot.")

    _lock(host)
    clash = overlapping(live_slots().filter(host=host), start, end).first()
    if clash:
        raise SlotError(
            f"This overlaps your slot at {local_time(clash.starts_at)}"
            f"–{local_time(clash.ends_at)}."
        )
    if is_busy(host, start, end):
        raise SlotError("You have a meeting booked during this time.")

    slots = []
    while start + length <= end:
        slots.append(Slot(host=host, starts_at=start, ends_at=start + length))
        start += length
    for slot in slots:
        slot.save()
    return slots
