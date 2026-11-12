from datetime import datetime, time, timedelta
from types import SimpleNamespace

from django.db import transaction
from django.db.models import (
    Case,
    Count,
    F,
    IntegerField,
    Min,
    OuterRef,
    Q,
    Subquery,
    When,
)
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from simple_history.utils import bulk_update_with_history

from notifications.services import notify
from people.models import Person, phone_key
from tasks.services import can_assign

from . import whereabouts
from .models import (
    CallLog,
    FollowUp,
    HRAssessment,
    Interview,
    Offer,
    OfferRound,
    Requisition,
    SourcedNumber,
)


class StaleRequisition(Exception):
    """Someone saved the requisition after this form was opened."""


def visible_requisitions(companies, status=""):
    reqs = Requisition.objects.filter(
        company__in=companies, archived_at__isnull=True
    ).annotate(
        sourced_count=Count("sourced"),
        duplicate_count=Count("sourced", filter=Q(sourced__is_duplicate=True)),
    )
    # Open first, then fire fighting before urgent before the rest.
    reqs = reqs.annotate(
        rank=Case(
            When(urgency="fire_fighting", then=0),
            When(urgency="urgent", then=1),
            default=2,
        )
    ).order_by("status", "rank", "needed_by", "-created_at")
    return reqs.filter(status=status) if status else reqs


def save_requisition(form, version=None):
    """Save from a valid form. For an existing requisition, `version` must be the
    one the form was opened at; otherwise nothing is saved."""
    with transaction.atomic():
        if form.instance.pk:
            current = Requisition.objects.select_for_update().get(pk=form.instance.pk)
            if version != current.version:
                raise StaleRequisition
            form.instance.version = current.version + 1
        return form.save()


def close(requisition):
    # Requisitions are closed, never deleted: sourced numbers will point at them.
    requisition.status = Requisition.Status.CLOSED
    requisition.version += 1
    requisition.save(update_fields=["status", "version"])


def reopen(requisition):
    requisition.status = Requisition.Status.OPEN
    requisition.version += 1
    requisition.save(update_fields=["status", "version"])


def requisition_timeline(r):
    """Everything that has happened around a requisition, newest first, as
    (when, who, text). Built from the records and their history, not stored."""
    events = [(r.created_at, r.opened_by, "Requisition released")]

    for rec in r.history.filter(history_type="~"):
        prev = rec.prev_record
        if not prev:
            continue
        fields = []
        for c in rec.diff_against(prev).changes:
            if c.field == "version":
                continue
            if c.field == "status":
                text = "Closed" if rec.status == "closed" else "Reopened"
                events.append((rec.history_date, rec.history_user, text))
            elif c.field == "urgency":
                text = f"Urgency changed to {rec.get_urgency_display().lower()}"
                events.append((rec.history_date, rec.history_user, text))
            else:
                fields.append(c.field.replace("_", " "))
        if fields:
            events.append(
                (rec.history_date, rec.history_user, "Edited " + ", ".join(fields))
            )

    for p in r.posts.select_related("author"):
        if p.is_job_post:
            events.append((p.created_at, p.author, f"Job post added on {p.portal}"))
            for rec in p.history.filter(history_type="~"):
                prev = rec.prev_record
                if prev and rec.post_status != prev.post_status:
                    status = rec.get_post_status_display().lower()
                    text = f"Job post on {rec.portal}: {status}"
                    events.append((rec.history_date, rec.history_user, text))
                elif prev:
                    events.append(
                        (
                            rec.history_date,
                            rec.history_user,
                            f"Job post on {rec.portal} edited",
                        )
                    )
        else:
            note = p.body if len(p.body) <= 80 else p.body[:77] + "..."
            events.append((p.created_at, p.author, f"Comment: {note}"))

    # One line per day, so a big sourcing day is one event, not a hundred.
    days = {}
    for s in r.sourced.select_related("sourced_by"):
        day = timezone.localtime(s.created_at).date()
        days.setdefault(day, []).append(s)
    for rows in days.values():
        n = len(rows)
        events.append(
            (
                rows[0].created_at,
                None,
                f"{n} number{'s' if n != 1 else ''} received",
            )
        )

    return sorted(events, key=lambda e: e[0], reverse=True)


def source_number(
    requisition, name, phone, user, source="", email="", address="", gender=""
):
    """Log a number received for a requisition. A new number makes a card; a
    number already on a card (last 10 digits, same company) links to it instead."""
    if len(phone_key(phone)) < 10:
        raise ValueError("Enter a phone number with at least 10 digits.")
    with transaction.atomic():
        person = (
            Person.objects.filter(
                company=requisition.company, phone_key=phone_key(phone)
            )
            .order_by("pk")
            .first()
        )
        duplicate = person is not None
        if not duplicate:
            person = Person.objects.create(
                company=requisition.company,
                name=name,
                phone=phone,
                email=email,
                address=address,
                gender=gender,
            )
        if not duplicate:
            # A new card goes straight into the sourcer's call queue.
            FollowUp.objects.create(
                person=person, requisition=requisition, due=timezone.now(), owner=user
            )
        return SourcedNumber.objects.create(
            requisition=requisition,
            person=person,
            source=source,
            is_duplicate=duplicate,
            sourced_by=user,
        )


def visible_sourced(companies, requisition=None, duplicates=False):
    rows = SourcedNumber.objects.filter(
        requisition__company__in=companies
    ).select_related("requisition", "person", "sourced_by")
    if requisition:
        rows = rows.filter(requisition=requisition)
    return rows.filter(is_duplicate=True) if duplicates else rows


def sources_in_use(companies):
    return list(
        SourcedNumber.objects.filter(requisition__company__in=companies)
        .exclude(source="")
        .values_list("source", flat=True)
        .distinct()
        .order_by("source")
    )


class FollowUpError(Exception):
    """The follow-up can't change that way; the message says why."""


def visible_followups(user, companies):
    """Pending follow-ups: your own, or everyone's for supervisors and admins."""
    rows = FollowUp.objects.filter(
        status=FollowUp.Status.PENDING, person__company__in=companies
    ).select_related("person", "requisition", "owner")
    if user.is_superuser or can_assign(user):
        return rows
    return rows.filter(owner=user)


def _pending(followup):
    # Re-read under a lock so a double submit can't act on it twice.
    current = FollowUp.objects.select_for_update().get(pk=followup.pk)
    if current.status != FollowUp.Status.PENDING:
        raise FollowUpError("That follow-up is already closed.")
    return current


def _open(after, purpose, due, other=""):
    """The next follow-up for the same person, unless one is already pending."""
    FollowUp.objects.get_or_create(
        person=after.person,
        purpose=purpose,
        status=FollowUp.Status.PENDING,
        defaults=dict(
            requisition=after.requisition,
            due=due,
            owner=after.owner,
            purpose_other=other,
        ),
    )


def log_call(
    followup,
    outcome,
    user,
    notes="",
    next_due=None,
    intention=FollowUp.Purpose.CALL,
    intention_other="",
    call_type=CallLog.Kind.OUTBOUND,
    rescheduled=False,
    reschedule_reason="",
    department_changed=False,
    discuss=False,
    mini_whereabout=None,
    major_whereabout=None,
    person=None,
):
    """Record a call: complete the follow-up and open the next one for `intention`.
    With no follow-up (a call that came in) it is logged for `person` alone.
    A department change, a discuss request or a whereabout form sends the card
    to the caller's supervisor."""
    mini_whereabout, major_whereabout = mini_whereabout or {}, major_whereabout or {}
    send = discuss or department_changed or mini_whereabout or major_whereabout
    boss = user.supervisor if send else None
    if send and not boss:
        raise FollowUpError("You have no supervisor set to send this to.")
    with transaction.atomic():
        current = _pending(followup) if followup else None
        person = current.person if current else person
        call = CallLog.objects.create(
            person=person,
            followup=current,
            caller=user,
            outcome=outcome,
            notes=notes,
            call_type=call_type,
            rescheduled=rescheduled,
            reschedule_reason=reschedule_reason,
            department_changed=department_changed,
            discussed=discuss,
            mini_whereabout=mini_whereabout,
            major_whereabout=major_whereabout,
        )
        if current:
            current.status = FollowUp.Status.COMPLETED
            current.version += 1
            current.save(update_fields=["status", "version"])
        if next_due:
            # shortcut: an incoming call's next follow-up is filed under the
            # candidate's latest requisition, and an already-pending follow-up
            # of the same kind is kept as it is.
            sourced = (
                person.sourced.select_related("requisition")
                .order_by("-created_at")
                .first()
            )
            after = current or SimpleNamespace(
                person=person,
                requisition=sourced.requisition if sourced else None,
                owner=user,
            )
            _open(after, intention, next_due, intention_other)
        if boss:
            why = (
                "a department change"
                if department_changed
                else "a discussion"
                if discuss
                else "a look at a whereabout form"
            )
            notify(
                boss,
                f"{user.display_name} needs {why} with you: {person.name}",
                reverse("people:detail", args=[person.pk]),
            )
        return call


def reschedule(followup, due, reason):
    with transaction.atomic():
        current = _pending(followup)
        current.original_due = current.original_due or current.due
        current.snoozed_until = None
        current.due = due
        current.reschedule_reason = reason
        current.reschedule_count += 1
        current.version += 1
        current.save()
        return current


def cancel(followup):
    with transaction.atomic():
        current = _pending(followup)
        current.status = FollowUp.Status.CANCELLED
        current.version += 1
        current.save(update_fields=["status", "version"])


def bulk_reassign(followups, owner, by):
    """Give many pending follow-ups to `owner` at once; they get one notice."""
    with transaction.atomic():
        rows = list(
            followups.select_related(None).exclude(owner=owner).select_for_update()
        )
        for f in rows:
            f.reassigned_from_id = f.owner_id
            f.owner = owner
            f.version += 1
        bulk_update_with_history(
            rows,
            FollowUp,
            ["owner", "reassigned_from", "version"],
            batch_size=1000,
            default_user=by,
        )
        if rows:
            notify(
                owner,
                f"{by.display_name} gave you {len(rows)} follow-ups",
                reverse("hiring:calling"),
            )
    return len(rows)


def bulk_move(followups, day, reason):
    """Move many pending follow-ups to `day`, each keeping its time of day and
    its first date, and counting the move."""
    with transaction.atomic():
        rows = list(followups.select_related(None).select_for_update())
        for f in rows:
            at = timezone.localtime(f.due).time()
            f.original_due = f.original_due or f.due
            f.snoozed_until = None
            f.due = timezone.make_aware(datetime.combine(day, at))
            f.reschedule_reason = reason
            f.reschedule_count += 1
            f.version += 1
        bulk_update_with_history(
            rows,
            FollowUp,
            [
                "original_due",
                "snoozed_until",
                "due",
                "reschedule_reason",
                "reschedule_count",
                "version",
            ],
            batch_size=1000,
        )
    return len(rows)


def reassign(followup, owner, by):
    with transaction.atomic():
        current = _pending(followup)
        if owner != current.owner:
            current.reassigned_from = current.owner
            current.owner = owner
            current.version += 1
            current.save()
            notify(
                owner,
                f"{by} gave you a call: {current.person.name}",
                reverse("hiring:screening"),
            )
        return current


def interviews_waiting(user, companies):
    return visible_followups(user, companies).filter(purpose=FollowUp.Purpose.INTERVIEW)


def record_interview(followup, result, user, questions="", notes="", next_due=None):
    """Record how an interview went. It completes the booking, and what happens
    next follows the result: selected opens an offer, hold opens a call if a date
    is given, rejected ends it."""
    with transaction.atomic():
        current = _pending(followup)
        interview = Interview.objects.create(
            person=current.person,
            requisition=current.requisition,
            followup=current,
            scheduled_at=current.due,
            result=result,
            questions=questions,
            notes=notes,
            interviewer=user,
        )
        current.status = FollowUp.Status.COMPLETED
        current.version += 1
        current.save(update_fields=["status", "version"])
        nxt = {
            Interview.Result.SELECTED: (FollowUp.Purpose.OFFER, timezone.now()),
            Interview.Result.HOLD: (FollowUp.Purpose.CALL, next_due),
        }.get(result)
        if nxt and nxt[1]:
            _open(current, *nxt)
        return interview


def visible_interviews(companies):
    return Interview.objects.filter(person__company__in=companies).select_related(
        "person", "requisition", "hr"
    )


def save_assessment(interview, decision, level, user, hold_tenure="", comments=""):
    return HRAssessment.objects.update_or_create(
        interview=interview,
        defaults=dict(
            decision=decision,
            level=level,
            hold_tenure=hold_tenure,
            comments=comments,
            assessor=user,
        ),
    )[0]


class OfferError(FollowUpError):
    """The offer can't change that way; the message says why."""


def offers_waiting(user, companies):
    return visible_followups(user, companies).filter(purpose=FollowUp.Purpose.OFFER)


def visible_offers(companies):
    return (
        Offer.objects.filter(person__company__in=companies)
        .select_related("person", "requisition")
        .prefetch_related("rounds")
    )


def start_offer(followup, amount, user, note=""):
    """Make the first offer for a candidate whose interview went well."""
    with transaction.atomic():
        current = _pending(followup)
        offer = Offer.objects.create(
            person=current.person, requisition=current.requisition, made_by=user
        )
        OfferRound.objects.create(offer=offer, amount=amount, note=note, by=user)
        current.status = FollowUp.Status.COMPLETED
        current.version += 1
        current.save(update_fields=["status", "version"])
        return offer


def _open_offer(offer):
    current = Offer.objects.select_for_update().get(pk=offer.pk)
    if current.state != Offer.State.OFFERED:
        raise OfferError("That offer is already closed.")
    return current


def add_round(offer, amount, user, counter=None, note=""):
    with transaction.atomic():
        current = _open_offer(offer)
        return OfferRound.objects.create(
            offer=current, amount=amount, counter=counter, note=note, by=user
        )


def accept(offer, joining_date, user):
    """The candidate said yes: close the offer and book the joining."""
    with transaction.atomic():
        current = _open_offer(offer)
        current.state = Offer.State.ACCEPTED
        current.joining_date = joining_date
        current.decided_at = timezone.now()
        current.save()
        FollowUp.objects.get_or_create(
            person=current.person,
            purpose=FollowUp.Purpose.JOINING,
            status=FollowUp.Status.PENDING,
            defaults=dict(
                requisition=current.requisition,
                due=timezone.make_aware(datetime.combine(joining_date, time(9))),
                owner=user,
            ),
        )
        return current


def decline(offer, reason=""):
    with transaction.atomic():
        current = _open_offer(offer)
        current.state = Offer.State.DECLINED
        current.decline_reason = reason
        current.decided_at = timezone.now()
        current.save()
        return current


def onboarding(companies):
    """Accepted offers: (still to join, joined)."""
    accepted = visible_offers(companies).filter(state=Offer.State.ACCEPTED)
    return (
        accepted.filter(joined_on__isnull=True).order_by("joining_date"),
        accepted.filter(joined_on__isnull=False).order_by("-joined_on"),
    )


def mark_joined(offer, on):
    """They turned up. Records the day and closes the joining follow-up."""
    with transaction.atomic():
        current = Offer.objects.select_for_update().get(pk=offer.pk)
        if current.state != Offer.State.ACCEPTED or current.joined_on:
            raise OfferError("That candidate is not waiting to join.")
        current.joined_on = on
        current.save(update_fields=["joined_on"])
        FollowUp.objects.filter(
            person=current.person,
            purpose=FollowUp.Purpose.JOINING,
            status=FollowUp.Status.PENDING,
        ).update(status=FollowUp.Status.COMPLETED)
        return current


def funnel(companies):
    """Requisitions with how many people reached each step. People are counted
    once per step, so a candidate called five times is still one call."""

    def reached(model, group="requisition", person="person", **kw):
        # A count of its own per step: joining every step at once multiplies the
        # rows and takes minutes at ten thousand candidates.
        rows = (
            model.objects.filter(**{group: OuterRef("pk")}, **kw)
            .order_by()
            .values(group)
            .annotate(n=Count(person, distinct=True))
            .values("n")
        )
        return Coalesce(Subquery(rows, output_field=IntegerField()), 0)

    return (
        Requisition.objects.filter(company__in=companies, archived_at__isnull=True)
        .annotate(
            sourced_n=reached(SourcedNumber, person="pk"),
            duplicate_n=reached(SourcedNumber, person="pk", is_duplicate=True),
            called_n=reached(CallLog, group="followup__requisition"),
            interviewed_n=reached(Interview),
            selected_n=reached(Interview, result="selected"),
            offered_n=reached(Offer),
            accepted_n=reached(Offer, state="accepted"),
            joined_n=reached(Offer, joined_on__isnull=False),
        )
        .order_by("status", "needed_by", "-created_at")
    )


def _at(when):
    return f"{timezone.localtime(when):%d %b %H:%M}"


def timeline(person, with_hr=False):
    """Everything that has happened around a card, newest first, as
    (when, who, text). Built from the records and their history, not stored."""
    events = [(person.created_at, None, "Card created")]

    # Person edits: the "~" history rows, naming the fields that changed.
    for rec in person.history.filter(history_type="~"):
        prev = rec.prev_record
        if not prev:
            continue
        fields = [
            c.field.replace("_", " ")
            for c in rec.diff_against(prev).changes
            if c.field != "version"
        ]
        if fields:
            events.append(
                (rec.history_date, rec.history_user, "Edited " + ", ".join(fields))
            )

    for s in person.sourced.select_related("requisition", "sourced_by"):
        text = f"Number received for {s.requisition.profile}"
        if s.source:
            text += f" via {s.source}"
        if s.is_duplicate:
            text += " (already on this card)"
        events.append((s.created_at, s.sourced_by, text))

    for f in person.followups.all():
        label = f.get_purpose_display().lower()
        events.append(
            (
                f.created_at,
                None,
                f"{label.capitalize()} booked for {_at(f.due)}",
            )
        )
        for rec in f.history.filter(history_type="~"):
            prev = rec.prev_record
            if not prev:
                continue
            if rec.due != prev.due:
                text = (
                    f"{label.capitalize()} moved from {_at(prev.due)} to {_at(rec.due)}"
                )
                if rec.reschedule_reason:
                    text += f" ({rec.get_reschedule_reason_display().lower()})"
                events.append((rec.history_date, rec.history_user, text))
            if rec.owner_id != prev.owner_id:
                events.append(
                    (
                        rec.history_date,
                        rec.history_user,
                        f"{label.capitalize()} given to {f.owner}",
                    )
                )
            if rec.status != prev.status and rec.status in ("cancelled", "not_done"):
                events.append(
                    (
                        rec.history_date,
                        rec.history_user,
                        f"{label.capitalize()} {rec.get_status_display().lower()}",
                    )
                )

    for c in person.calls.select_related("caller"):
        text = f"Call: {c.get_outcome_display()}"
        if c.notes:
            text += f". {c.notes}"
        for name, answers in (
            ("Mini whereabout", c.mini_whereabout),
            ("Major whereabout", c.major_whereabout),
        ):
            if answers:
                text += f" {name}: {whereabouts.summary(answers)}."
        events.append((c.called_at, c.caller, text))

    for i in person.interviews.select_related("interviewer"):
        text = f"Interview: {i.get_result_display().lower()}"
        events.append(
            (i.scheduled_at, i.interviewer, f"{text}. {i.notes}" if i.notes else text)
        )
        if with_hr and hasattr(i, "hr"):
            h = i.hr
            events.append(
                (
                    h.created_at,
                    h.assessor,
                    f"HR assessment: {h.get_decision_display().lower()}, "
                    f"{h.get_level_display().lower()}",
                )
            )

    for o in person.offers.select_related("made_by"):
        events.append((o.created_at, o.made_by, "Offer made"))
        for r in o.rounds.select_related("by"):
            text = f"Offer round: {r.amount}"
            if r.counter is not None:
                text += f", candidate asked {r.counter}"
            events.append((r.created_at, r.by, text))
        if o.decided_at:
            text = (
                "Offer accepted, joining " + f"{o.joining_date:%d %b %Y}"
                if o.state == "accepted"
                else "Offer declined"
            )
            events.append((o.decided_at, None, text))
        if o.joined_on:
            events.append(
                (
                    timezone.make_aware(datetime.combine(o.joined_on, time(9))),
                    None,
                    "Joined",
                )
            )

    return sorted(events, key=lambda e: e[0], reverse=True)


def stage(person):
    """Where a candidate is now, worked out from what exists, never stored."""
    offers = list(person.offers.all())
    if any(o.joined_on for o in offers):
        return "Working"
    if any(o.state == Offer.State.ACCEPTED for o in offers):
        return "On-Boarding"
    pending = set(
        person.followups.filter(status=FollowUp.Status.PENDING).values_list(
            "purpose", flat=True
        )
    )
    if any(o.state == Offer.State.OFFERED for o in offers) or "offer" in pending:
        return "Hiring"
    if "interview" in pending:
        return "Selecting"
    if offers:
        return "Offer declined"
    last = person.interviews.first()
    if last:
        return "Not selected" if last.result == "rejected" else "Selecting"
    if person.calls.exists() or pending:
        return "Screening"
    return "Sourcing"


def schedule_call(person, due, user):
    """Book a call for a card that has none pending (a new number books its own)."""
    with transaction.atomic():
        existing = person.followups.filter(
            status=FollowUp.Status.PENDING, purpose=FollowUp.Purpose.CALL
        ).first()
        if existing:
            raise FollowUpError(
                f"A call is already booked for {_at(existing.due)}. "
                "Move that one instead."
            )
        last = person.sourced.first()
        return FollowUp.objects.create(
            person=person,
            requisition=last.requisition if last else None,
            purpose=FollowUp.Purpose.CALL,
            due=due,
            owner=user,
        )


def shift_calls(followups, day, reason):
    """Move pending calls to `day`, each keeping its time of day. For the days
    staff are out or the queue is too long to get through."""
    moved = 0
    with transaction.atomic():
        for f in followups:
            if f.purpose != FollowUp.Purpose.CALL:
                continue
            at = timezone.localtime(f.due).time()
            reschedule(f, timezone.make_aware(datetime.combine(day, at)), reason)
            moved += 1
    return moved


RINGING = (FollowUp.Purpose.CALL, FollowUp.Purpose.INTERVIEW)


def _alarmed(user):
    return FollowUp.objects.filter(
        owner=user, status=FollowUp.Status.PENDING, purpose__in=RINGING
    ).select_related("person")


def due_call_alarms(user):
    """Calls and interviews of the user's whose time has come, until they're done."""
    now = timezone.now()
    return (
        _alarmed(user)
        .filter(due__lte=now)
        .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lte=now))
        .order_by("due")
    )


def quiet_call_alarms(user):
    """Silence every ringing call and interview alarm of the user's for an hour."""
    due_call_alarms(user).update(snoozed_until=timezone.now() + timedelta(hours=1))


def next_call_alarm_in(user):
    """Seconds until the user's next call alarm, or None."""
    now = timezone.now()
    soonest = (
        _alarmed(user)
        .filter(Q(due__gt=now) | Q(snoozed_until__gt=now))
        .annotate(
            rings=Case(
                When(snoozed_until__gt=now, then=F("snoozed_until")), default=F("due")
            )
        )
        .aggregate(at=Min("rings"))["at"]
    )
    return max((soonest - now).total_seconds(), 0) if soonest else None


def snooze_call(followup, user, length):
    """Quiet the alarm for a while; the follow-up itself stays due."""
    from tasks.services import SNOOZES

    with transaction.atomic():
        current = _pending(followup)
        if current.owner_id != user.pk:
            raise FollowUpError("Only the person it belongs to can snooze it.")
        now = timezone.now()
        if length == "tomorrow":
            morning = timezone.localtime(now).replace(hour=9, minute=0, second=0)
            current.snoozed_until = morning + timedelta(days=1)
        elif length in SNOOZES:
            current.snoozed_until = now + SNOOZES[length]
        else:
            raise FollowUpError("Choose how long to snooze.")
        current.save(update_fields=["snoozed_until"])
        return current


def edit_interview(interview, result, questions, notes):
    """Correct a saved interview. If it now reads "selected", the offer opens as
    it would have the first time; a move away from selected leaves the offer
    follow-up for someone to cancel."""
    with transaction.atomic():
        interview.result = result
        interview.questions = questions
        interview.notes = notes
        interview.save()
        person = interview.person
        if result == Interview.Result.SELECTED and not person.offers.exists():
            FollowUp.objects.get_or_create(
                person=person,
                purpose=FollowUp.Purpose.OFFER,
                status=FollowUp.Status.PENDING,
                defaults=dict(
                    requisition=interview.requisition,
                    due=timezone.now(),
                    owner=interview.interviewer,
                ),
            )
        return interview


def by_source(rows):
    """Per source: (source, numbers received, duplicates, duplicate rate)."""
    return [
        (r["source"] or "(none)", r["total"], r["dups"], r["dups"] / r["total"])
        for r in rows.order_by()
        .values("source")
        .annotate(total=Count("id"), dups=Count("id", filter=Q(is_duplicate=True)))
        .order_by("source")
    ]
