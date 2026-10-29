from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from chat.services import post_notice

from .models import Conference, Invitation, Slot, SlotRequest

BLOCK_REASON_MAX = 200


class SlotError(Exception):
    """A request that breaks a scheduling rule; the message is shown to the user."""


def live_slots():
    return Slot.objects.filter(cancelled_at__isnull=True)


def overlapping(slots, start, end):
    return slots.filter(starts_at__lt=end, ends_at__gt=start)


def live_conferences():
    return Conference.objects.filter(cancelled_at__isnull=True)


def attending(user):
    """Live conferences the user hosts or has accepted."""
    accepted = Q(invitations__user=user, invitations__status=Invitation.Status.ACCEPTED)
    return live_conferences().filter(Q(host=user) | accepted)


def is_busy(user, start, end, ignore=None):
    """Whether the user has a booked meeting or a conference in this time.

    `ignore` is a conference to leave out, when checking whether it clashes.
    """
    booked = live_slots().filter(booked_by__isnull=False)
    mine = booked.filter(Q(host=user) | Q(booked_by=user))
    if overlapping(mine, start, end).exists():
        return True
    others = attending(user)
    if ignore:
        others = others.exclude(pk=ignore.pk)
    return overlapping(others, start, end).exists()


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
        _close_requests(slot, user, f"can't give you {describe(slot)} any more")
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
        slot.reminded_at = None
        slot.cancelled_at = None
        slot.block_reason = ""
        slot.save()
        opened += 1
    return opened


REMINDER_LEAD = timedelta(minutes=10)


def send_reminders(now=None):
    """Tell both people about meetings starting within REMINDER_LEAD. Returns how many.

    Run every minute (see deploy/). Each meeting is reminded once: reminded_at
    is set in the same transaction as the notices, so a crash sends nothing and
    the next run tries again.
    """
    now = now or timezone.now()
    sent = 0
    with transaction.atomic():
        due = (
            live_slots()
            .select_for_update(of=("self",))
            .filter(
                booked_by__isnull=False,
                reminded_at__isnull=True,
                starts_at__gt=now,
                starts_at__lte=now + REMINDER_LEAD,
            )
            .select_related("host", "booked_by")
        )
        for slot in due:
            when = f"{local_time(slot.starts_at)}–{local_time(slot.ends_at)}"
            for me, other in ((slot.host, slot.booked_by), (slot.booked_by, slot.host)):
                post_notice(
                    other,
                    me,
                    f"Reminder: you have time with {other.display_name} at {when}. "
                    f"Topic: {slot.topic}",
                )
            # update(), not save(): a reminder is not an edit worth a history row.
            Slot.objects.filter(pk=slot.pk).update(reminded_at=now)
            sent += 1
        sent += _remind_conferences(now)
    return sent


def _remind_conferences(now):
    """Remind the host and everyone who accepted; returns how many conferences.

    A conference nobody has accepted yet is left for the next run, so the first
    people to accept before it starts still get reminded.
    """
    sent = 0
    due = (
        live_conferences()
        .select_for_update(of=("self",))
        .filter(
            reminded_at__isnull=True,
            starts_at__gt=now,
            starts_at__lte=now + REMINDER_LEAD,
        )
        .select_related("host")
    )
    for conference in due:
        going = [
            i.user
            for i in conference.invitations.filter(
                status=Invitation.Status.ACCEPTED, user__is_active=True
            ).select_related("user")
        ]
        if not going:
            continue
        when = f"{local_time(conference.starts_at)}–{local_time(conference.ends_at)}"
        where = f" at {conference.location}" if conference.location else ""
        for person in going:
            post_notice(
                conference.host,
                person,
                f"Reminder: {conference.title} starts at {when}{where}.",
            )
        post_notice(
            going[0],
            conference.host,
            f"Reminder: {conference.title} starts at {when}{where}. "
            f"{len(going)} accepted.",
        )
        Conference.objects.filter(pk=conference.pk).update(reminded_at=now)
        sent += 1
    return sent


def describe(slot):
    """'Thu 22 Oct, 10:30–11:00' in local time."""
    start = timezone.localtime(slot.starts_at)
    day = f"{start:%a} {start.day} {start:%b}"
    return f"{day}, {local_time(slot.starts_at)}–{local_time(slot.ends_at)}"


def _check_requestable(slot, requester):
    """Raise SlotError unless the slot can be taken by the requester right now."""
    if slot.is_cancelled:
        raise SlotError("This slot has been removed.")
    if slot.is_booked:
        raise SlotError("Sorry, someone just took this slot.")
    if slot.starts_at <= timezone.now():
        raise SlotError("This slot has already started.")
    if is_busy(requester, slot.starts_at, slot.ends_at):
        raise SlotError("You already have something booked at this time.")
    if is_busy(slot.host, slot.starts_at, slot.ends_at):
        raise SlotError(f"{slot.host.display_name} is no longer free at this time.")


def _close_requests(slot, author, text, except_pk=None):
    """Decline the slot's waiting requests, telling each person why."""
    waiting = slot.requests.filter(status=SlotRequest.Status.PENDING)
    if except_pk:
        waiting = waiting.exclude(pk=except_pk)
    for request in waiting.select_related("requester"):
        request.status = SlotRequest.Status.DECLINED
        request.responded_at = timezone.now()
        request.save()
        post_notice(author, request.requester, text)


@transaction.atomic
def request_slot(slot, user, topic):
    """Ask the host for a free slot. Nothing is booked until they accept."""
    topic = topic.strip()
    if not topic:
        raise SlotError("Say what you want to discuss.")
    if slot.host_id == user.pk:
        raise SlotError("You can't ask for your own slot.")

    _lock(slot.host, user)
    slot = Slot.objects.select_for_update().select_related("host").get(pk=slot.pk)
    _check_requestable(slot, user)
    if slot.requests.filter(requester=user, status=SlotRequest.Status.PENDING).exists():
        raise SlotError("You've already asked for this time.")

    request = SlotRequest.objects.create(slot=slot, requester=user, topic=topic)
    post_notice(user, slot.host, f"asked for your time {describe(slot)}: {topic}")
    return request


@transaction.atomic
def accept_request(request, user):
    """The host agrees: this is the only way a slot gets booked."""
    request = SlotRequest.objects.select_related("slot__host", "requester").get(
        pk=request.pk
    )
    host, requester = request.slot.host, request.requester
    if user.pk != host.pk:
        raise PermissionDenied("Only the host can accept a request.")

    _lock(host, requester)
    request = SlotRequest.objects.select_for_update(of=("self",)).get(pk=request.pk)
    slot = (
        Slot.objects.select_for_update().select_related("host").get(pk=request.slot_id)
    )
    if not request.is_pending:
        raise SlotError("This request has already been answered.")
    _check_requestable(slot, requester)

    slot.booked_by = requester
    slot.topic = request.topic
    slot.booked_at = timezone.now()
    slot.reminded_at = None
    slot.save()
    request.status = SlotRequest.Status.ACCEPTED
    request.responded_at = timezone.now()
    request.save()
    post_notice(
        host, requester, f"accepted your request for {describe(slot)}: {request.topic}"
    )
    _close_requests(
        slot,
        host,
        f"couldn't give you {describe(slot)}, it went to someone else",
        except_pk=request.pk,
    )
    return slot


@transaction.atomic
def decline_request(request, user):
    request = SlotRequest.objects.select_related("slot__host", "requester").get(
        pk=request.pk
    )
    if user.pk != request.slot.host_id:
        raise PermissionDenied("Only the host can decline a request.")
    request = SlotRequest.objects.select_for_update(of=("self",)).get(pk=request.pk)
    if not request.is_pending:
        raise SlotError("This request has already been answered.")
    request.status = SlotRequest.Status.DECLINED
    request.responded_at = timezone.now()
    request.save()
    post_notice(
        user,
        request.requester,
        f"declined your request for {describe(request.slot)}: {request.topic}",
    )
    return request


@transaction.atomic
def withdraw_request(request, user):
    request = (
        SlotRequest.objects.select_for_update(of=("self",))
        .select_related("slot__host")
        .get(pk=request.pk)
    )
    if user.pk != request.requester_id:
        raise PermissionDenied("Only the person who asked can withdraw.")
    if not request.is_pending:
        raise SlotError("This request has already been answered.")
    request.status = SlotRequest.Status.WITHDRAWN
    request.responded_at = timezone.now()
    request.save()
    post_notice(
        user,
        request.slot.host,
        f"withdrew their request for {describe(request.slot)}: {request.topic}",
    )
    return request


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
        raise SlotError("This time is already over.")

    when = f"{describe(slot)} ({slot.topic})" if slot.is_booked else describe(slot)
    if user.pk == slot.booked_by_id:
        slot.booked_by = None
        slot.topic = ""
        slot.booked_at = None
        slot.reminded_at = None
        slot.save()
        slot.requests.filter(requester=user, status=SlotRequest.Status.ACCEPTED).update(
            status=SlotRequest.Status.WITHDRAWN
        )
        post_notice(user, slot.host, f"cancelled their booking for {when}")
        return slot

    guest = slot.booked_by
    slot.cancelled_at = timezone.now()
    slot.save()
    _close_requests(slot, user, f"can't give you {describe(slot)} any more")
    if guest:
        post_notice(user, guest, f"cancelled your booking for {when}")
    return slot


CONFERENCE_TITLE_MAX = 200


def _active_users(users):
    return [user for user in users if user.is_active]


def _clean_conference(title, start, end, location):
    title = title.strip()
    if not title:
        raise SlotError("Give the conference a title.")
    if len(title) > CONFERENCE_TITLE_MAX:
        raise SlotError(f"Keep the title under {CONFERENCE_TITLE_MAX} characters.")
    if end <= start:
        raise SlotError("The conference must end after it starts.")
    if start <= timezone.now():
        raise SlotError("The conference must start in the future.")
    return title, location.strip()


def conference_clashes(users, start, end, conference=None):
    """Of these people, those already busy in this time, so the host can be warned."""
    return [user for user in users if is_busy(user, start, end, ignore=conference)]


@transaction.atomic
def create_conference(host, title, start, end, invitees, agenda="", location=""):
    """Create a conference and invite people. Clashes are warned about, not refused."""
    title, location = _clean_conference(title, start, end, location)
    people = [u for u in _active_users(invitees) if u.pk != host.pk]
    conference = Conference.objects.create(
        host=host,
        title=title,
        agenda=agenda.strip(),
        location=location,
        starts_at=start,
        ends_at=end,
    )
    for person in people:
        invite(conference, person, notify=False)
        post_notice(host, person, _invited_text(conference))
    return conference


def _invited_text(conference):
    where = f" at {conference.location}" if conference.location else ""
    return f"invited you to {conference.title}, {describe(conference)}{where}"


def _live_conference(conference):
    conference = Conference.objects.select_for_update().get(pk=conference.pk)
    if conference.is_cancelled:
        raise SlotError("This conference has been cancelled.")
    if conference.ends_at <= timezone.now():
        raise SlotError("This conference is already over.")
    return conference


def _require_host(conference, user):
    if conference.host_id != user.pk:
        raise PermissionDenied("Only the host can change this conference.")


@transaction.atomic
def invite(conference, person, notify=True):
    if person.pk == conference.host_id:
        raise SlotError("The host is already attending.")
    invitation, created = Invitation.objects.get_or_create(
        conference=conference, user=person
    )
    if created and notify:
        post_notice(conference.host, person, _invited_text(conference))
    return invitation


@transaction.atomic
def add_invitees(conference, host, people):
    conference = _live_conference(conference)
    _require_host(conference, host)
    added = []
    for person in _active_users(people):
        if (
            person.pk != host.pk
            and not conference.invitations.filter(user=person).exists()
        ):
            added.append(invite(conference, person))
    return added


@transaction.atomic
def remove_invitee(conference, host, person):
    conference = _live_conference(conference)
    _require_host(conference, host)
    removed, _ = conference.invitations.filter(user=person).delete()
    if removed:
        post_notice(
            host, person, f"removed you from {conference.title}, {describe(conference)}"
        )
    return bool(removed)


@transaction.atomic
def respond(conference, user, accept):
    """An invitee accepts or declines; the host is told."""
    conference = _live_conference(conference)
    _lock(user)
    try:
        invitation = conference.invitations.select_for_update().get(user=user)
    except Invitation.DoesNotExist:
        raise PermissionDenied("You aren't invited to this conference.") from None
    invitation.status = (
        Invitation.Status.ACCEPTED if accept else Invitation.Status.DECLINED
    )
    invitation.responded_at = timezone.now()
    invitation.save()
    verb = "accepted" if accept else "declined"
    post_notice(
        user, conference.host, f"{verb} {conference.title}, {describe(conference)}"
    )
    return invitation


@transaction.atomic
def cancel_conference(conference, host):
    conference = _live_conference(conference)
    _require_host(conference, host)
    conference.cancelled_at = timezone.now()
    conference.save()
    for invitation in conference.invitations.exclude(
        status=Invitation.Status.DECLINED
    ).select_related("user"):
        post_notice(
            host,
            invitation.user,
            f"cancelled {conference.title}, {describe(conference)}",
        )
    return conference


@transaction.atomic
def edit_conference(conference, host, title, start, end, agenda="", location=""):
    """Change a conference. A new time asks everyone who hasn't declined again."""
    conference = _live_conference(conference)
    _require_host(conference, host)
    title, location = _clean_conference(title, start, end, location)
    moved = (start, end) != (conference.starts_at, conference.ends_at)
    conference.title, conference.location = title, location
    conference.agenda = agenda.strip()
    conference.starts_at, conference.ends_at = start, end
    if moved:
        conference.reminded_at = None
    conference.save()
    people = conference.invitations.exclude(status=Invitation.Status.DECLINED)
    if moved:
        people.filter(status=Invitation.Status.ACCEPTED).update(
            status=Invitation.Status.INVITED, responded_at=None
        )
    ask = " Please accept again." if moved else ""
    for invitation in people.select_related("user"):
        post_notice(
            host,
            invitation.user,
            f"changed {conference.title}: {describe(conference)}.{ask}",
        )
    return conference
