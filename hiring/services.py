from datetime import datetime, time

from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from notifications.services import notify
from people.models import Person, phone_key
from tasks.services import can_assign

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


def source_number(requisition, name, phone, user, source="", email=""):
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
                company=requisition.company, name=name, phone=phone, email=email
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


def _open(after, purpose, due):
    """The next follow-up for the same person, unless one is already pending."""
    FollowUp.objects.get_or_create(
        person=after.person,
        purpose=purpose,
        status=FollowUp.Status.PENDING,
        defaults=dict(requisition=after.requisition, due=due, owner=after.owner),
    )


# Outcomes that need a next date, and the follow-up they open.
NEXT = {
    CallLog.Outcome.INTERESTED: FollowUp.Purpose.CALL,
    CallLog.Outcome.CALL_BACK: FollowUp.Purpose.CALL,
    CallLog.Outcome.NO_ANSWER: FollowUp.Purpose.CALL,
    CallLog.Outcome.INTERVIEW: FollowUp.Purpose.INTERVIEW,
}


def log_call(followup, outcome, user, notes="", next_due=None):
    """Record a call: complete the follow-up, then open the next one if the
    outcome calls for it (a date is required then)."""
    purpose = NEXT.get(outcome)
    if purpose and not next_due:
        raise FollowUpError("Pick when to follow up next.")
    with transaction.atomic():
        current = _pending(followup)
        call = CallLog.objects.create(
            person=current.person,
            followup=current,
            caller=user,
            outcome=outcome,
            notes=notes,
        )
        current.status = FollowUp.Status.COMPLETED
        current.version += 1
        current.save(update_fields=["status", "version"])
        if purpose:
            _open(current, purpose, next_due)
        if outcome == CallLog.Outcome.DO_NOT_CALL:
            current.person.contact_status = current.person.ContactStatus.DO_NOT_CALL
            current.person.version += 1
            current.person.save(update_fields=["contact_status", "version"])
        return call


def reschedule(followup, due, reason):
    with transaction.atomic():
        current = _pending(followup)
        current.original_due = current.original_due or current.due
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
    return Offer.objects.filter(person__company__in=companies).select_related(
        "person", "requisition"
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
    done = lambda path, **kw: Count(path, distinct=True, filter=Q(**kw) if kw else None)  # noqa: E731
    return (
        Requisition.objects.filter(company__in=companies, archived_at__isnull=True)
        .annotate(
            sourced_n=done("sourced"),
            duplicate_n=done("sourced", sourced__is_duplicate=True),
            called_n=done("followups__calls__person"),
            interviewed_n=done("interviews__person"),
            selected_n=done("interviews__person", interviews__result="selected"),
            offered_n=done("offers__person"),
            accepted_n=done("offers__person", offers__state="accepted"),
            joined_n=done("offers__person", offers__joined_on__isnull=False),
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
        text = f"Call: {c.get_outcome_display().lower()}"
        events.append(
            (c.called_at, c.caller, f"{text}. {c.notes}" if c.notes else text)
        )

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
