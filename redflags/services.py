from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.urls import reverse

from notifications.services import notify

from .models import Attachment, Note, RedFlag, Status


class RedFlagError(Exception):
    """A change that can't be made; the message is shown to the person."""


def can_read(user):
    """Only superadmins read red flags. Not Office admins, not trainers. This is
    the one place that decides it.
    """
    return user.is_active and user.is_superuser


def readers():
    return get_user_model().objects.filter(is_active=True, is_superuser=True)


def visible_flags(user):
    """Everything for a superadmin, nothing for anyone else."""
    flags = RedFlag.objects.prefetch_related("attachments")
    return flags if can_read(user) else flags.none()


@transaction.atomic
def submit(user, against, incident_date, incident, files=()):
    """Record a flag and tell the superadmins, with no details in the notice."""
    flag = RedFlag.objects.create(
        raised_by=user,
        raised_by_name=user.display_name,
        raised_against=against,
        raised_against_name=against.display_name,
        incident_date=incident_date,
        incident=incident,
    )
    for upload in files:
        Attachment.objects.create(
            red_flag=flag, file=upload, original_name=upload.name, size=upload.size
        )
    link = reverse("redflags:detail", args=[flag.pk])
    for admin in readers().exclude(pk=user.pk):
        notify(admin, "A new red flag was raised", link)
    return flag


@transaction.atomic
def add_note(flag, user, body):
    if not can_read(user):
        raise PermissionDenied("Only superadmins read red flags.")
    return Note.objects.create(red_flag=flag, author=user, body=body)


@transaction.atomic
def set_status(flag, user, status):
    if not can_read(user):
        raise PermissionDenied("Only superadmins read red flags.")
    if status not in Status.values:
        raise RedFlagError("That isn't a status.")
    flag.status = status
    flag.save(update_fields=["status"])
    return flag
