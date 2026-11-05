from django.db import transaction

from .models import Requisition


class StaleRequisition(Exception):
    """Someone saved the requisition after this form was opened."""


def visible_requisitions(companies, status=""):
    reqs = Requisition.objects.filter(company__in=companies, archived_at__isnull=True)
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
