from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from chat.services import post_notice

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


def describe(slot):
    """'Thu 22 Oct, 10:30–11:00' in local time."""
    start = timezone.localtime(slot.starts_at)
    day = f"{start:%a} {start.day} {start:%b}"
    return f"{day}, {local_time(slot.starts_at)}–{local_time(slot.ends_at)}"


@transaction.atomic
def book(slot, user, topic):
    """Book a free slot for the user. First come, first served."""
    topic = topic.strip()
    if not topic:
        raise SlotError("Say what the meeting is about.")
    if slot.host_id == user.pk:
        raise SlotError("You can't book your own slot.")

    _lock(slot.host, user)
    slot = Slot.objects.select_for_update().get(pk=slot.pk)
    if slot.is_cancelled:
        raise SlotError("This slot has been removed.")
    if slot.is_booked:
        raise SlotError("Sorry, someone just booked this slot.")
    if slot.starts_at <= timezone.now():
        raise SlotError("This slot has already started.")
    if is_busy(user, slot.starts_at, slot.ends_at):
        raise SlotError("You already have a meeting booked at this time.")
    if is_busy(slot.host, slot.starts_at, slot.ends_at):
        raise SlotError(f"{slot.host.username} is no longer free at this time.")

    slot.booked_by = user
    slot.topic = topic
    slot.booked_at = timezone.now()
    slot.save()
    post_notice(user, slot.host, f"booked your slot {describe(slot)}: {topic}")
    return slot
