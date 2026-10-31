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
