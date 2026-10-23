from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from chat.services import post_notice

from .models import Slot

BLOCK_REASON_MAX = 200


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


OFFICE_DAYS = range(6)  # Monday to Saturday
OFFICE_HOURS = [(time(10), time(13, 30)), (time(14), time(18))]  # lunch 13:30–14:00
OFFICE_SLOT = timedelta(minutes=15)


@transaction.atomic
def open_office_hours(host, day):
    """Open the host's office hours on this day as free slots others can book.

    A day is filled once: slots the host removes later don't come back. Times
    the host already has a slot or a meeting, and times already past, are skipped.
    """
    if day.weekday() not in OFFICE_DAYS:
        return []
    _lock(host)
    midnight = timezone.make_aware(datetime.combine(day, time.min))
    filled = Slot.objects.filter(
        host=host,
        office_hours=True,
        starts_at__gte=midnight,
        starts_at__lt=midnight + timedelta(days=1),
    )
    if filled.exists():
        return []

    day_start = timezone.make_aware(datetime.combine(day, OFFICE_HOURS[0][0]))
    day_end = timezone.make_aware(datetime.combine(day, OFFICE_HOURS[-1][1]))
    taken = overlapping(
        live_slots().filter(Q(host=host) | Q(booked_by=host)), day_start, day_end
    )
    taken = [(slot.starts_at, slot.ends_at) for slot in taken]

    slots = []
    for first, last in OFFICE_HOURS:
        start = timezone.make_aware(datetime.combine(day, first))
        end = timezone.make_aware(datetime.combine(day, last))
        while start + OFFICE_SLOT <= end:
            stop = start + OFFICE_SLOT
            clashes = any(s < stop and e > start for s, e in taken)
            if start >= timezone.now() and not clashes:
                slots.append(
                    Slot(host=host, starts_at=start, ends_at=stop, office_hours=True)
                )
            start = stop
    for slot in slots:
        slot.save()
    return slots


def office_days_open():
    """Today, until office hours end, and the next office day."""
    now = timezone.localtime()
    days = []
    if now.weekday() in OFFICE_DAYS and now.time() < OFFICE_HOURS[-1][1]:
        days.append(now.date())
    following = now.date() + timedelta(days=1)
    while following.weekday() not in OFFICE_DAYS:
        following += timedelta(days=1)
    days.append(following)
    return days


def open_upcoming_office_hours():
    """Open everyone's office hours for the days people can book, if not yet open.

    Called by the meetings pages, so there is no scheduled job. Usually it only
    finds that everyone is done already.
    """
    people = get_user_model().objects.filter(is_active=True)
    for day in office_days_open():
        midnight = timezone.make_aware(datetime.combine(day, time.min))
        done = Slot.objects.filter(
            office_hours=True,
            starts_at__gte=midnight,
            starts_at__lt=midnight + timedelta(days=1),
        ).values("host")
        for person in people.exclude(pk__in=done):
            open_office_hours(person, day)


def _own_future_slots(user, pks):
    return Slot.objects.select_for_update().filter(
        pk__in=pks, host=user, starts_at__gt=timezone.now()
    )


@transaction.atomic
def block(user, pks, reason):
    """Take the user's free slots out of booking for a reason. Returns how many.

    Slots someone booked in the meantime are left alone.
    """
    reason = reason.strip()
    if not reason:
        raise SlotError("Say why you're blocking this time.")
    if len(reason) > BLOCK_REASON_MAX:
        raise SlotError(f"Keep the reason under {BLOCK_REASON_MAX} characters.")
    _lock(user)
    slots = _own_future_slots(user, pks).filter(
        cancelled_at__isnull=True, booked_by__isnull=True
    )
    for slot in slots:
        slot.cancelled_at = timezone.now()
        slot.block_reason = reason
        slot.save()
    return len(slots)


@transaction.atomic
def unblock(user, pks):
    """Open the user's blocked slots for booking again. Returns how many.

    A slot that clashes with a meeting the user has since booked stays blocked.
    """
    _lock(user)
    mine = live_slots().filter(Q(host=user) | Q(booked_by=user))
    opened = 0
    for slot in _own_future_slots(user, pks).filter(cancelled_at__isnull=False):
        if overlapping(mine, slot.starts_at, slot.ends_at).exists():
            continue
        # A meeting the host cancelled leaves its booker behind; clear it so
        # unblocking doesn't bring the meeting back.
        slot.booked_by = None
        slot.topic = ""
        slot.booked_at = None
        slot.cancelled_at = None
        slot.block_reason = ""
        slot.save()
        opened += 1
    return opened


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
        raise SlotError(f"{slot.host.display_name} is no longer free at this time.")

    slot.booked_by = user
    slot.topic = topic
    slot.booked_at = timezone.now()
    slot.save()
    post_notice(user, slot.host, f"booked your slot {describe(slot)}: {topic}")
    return slot


@transaction.atomic
def cancel(slot, user):
    """The booker frees the slot again; the host removes it altogether."""
    slot = (
        Slot.objects.select_for_update(of=("self",))
        .select_related("host", "booked_by")
        .get(pk=slot.pk)
    )
    if user.pk not in (slot.host_id, slot.booked_by_id):
        raise PermissionDenied("Only the host and the booker can cancel.")
    if slot.is_cancelled:
        raise SlotError("This slot has already been removed.")
    if slot.ends_at <= timezone.now():
        raise SlotError("This meeting is already over.")

    when = f"{describe(slot)} ({slot.topic})" if slot.is_booked else describe(slot)
    if user.pk == slot.booked_by_id:
        slot.booked_by = None
        slot.topic = ""
        slot.booked_at = None
        slot.save()
        post_notice(user, slot.host, f"cancelled their booking for {when}")
        return slot

    guest = slot.booked_by
    slot.cancelled_at = timezone.now()
    slot.save()
    if guest:
        post_notice(user, guest, f"cancelled your booking for {when}")
    return slot
