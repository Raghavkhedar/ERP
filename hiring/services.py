from django.db import transaction
from django.db.models import Count, Q

from people.models import Person, phone_key

from .models import Requisition, SourcedNumber


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
