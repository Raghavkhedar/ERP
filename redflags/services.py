from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from notifications.services import notify

from .models import Attachment, Note, RedFlag, Status


class RedFlagError(Exception):
    """A change that can't be made; the message is shown to the person."""


def can_read(user):
    """Only superadmins read red flags. Not Office admins, not trainers. This is
    the one place that decides it.
    """
    return user.is_active and user.is_superuser


def has_access(user):
    """Superadmins, and supervisors a flag is currently assigned to."""
    if not user.is_active:
        return False
    return user.is_superuser or user.assigned_red_flags.exists()


def can_add_note(user, flag):
    return can_read(user) or (user.is_active and flag.assigned_to_id == user.pk)


def readers():
    return get_user_model().objects.filter(is_active=True, is_superuser=True)


def visible_flags(user):
    """Everything for a superadmin, only their assigned flags for a supervisor,
    nothing for anyone else.
    """
    flags = RedFlag.objects.prefetch_related("attachments")
    if can_read(user):
        return flags
    if user.is_active:
        return flags.filter(assigned_to=user)
    return flags.none()


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
    if not can_add_note(user, flag):
        raise PermissionDenied("You can't add notes to this red flag.")
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


def supervisor_of(flag, of):
    person = flag.raised_against if of == "against" else flag.raised_by
    return (
        person.supervisor if person.supervisor and person.supervisor.is_active else None
    )


@transaction.atomic
def assign_to_supervisor(flag, user, of):
    """Hand the flag to the supervisor of the person raised against, or of the
    person who raised it. The notice carries no details, like a new flag's.
    """
    if not can_read(user):
        raise PermissionDenied("Only superadmins assign red flags.")
    if of not in ("against", "raiser"):
        raise RedFlagError("Choose whose supervisor to assign it to.")
    supervisor = supervisor_of(flag, of)
    name = flag.raised_against_name if of == "against" else flag.raised_by_name
    if supervisor is None:
        raise RedFlagError(f"{name} has no supervisor set.")
    flag.assigned_to = supervisor
    flag.assigned_on = timezone.localdate()
    flag.save(update_fields=["assigned_to", "assigned_on"])
    notify(
        supervisor,
        "A red flag was assigned to you",
        reverse("redflags:detail", args=[flag.pk]),
    )
    return flag


@transaction.atomic
def unassign(flag, user):
    if not can_read(user):
        raise PermissionDenied("Only superadmins assign red flags.")
    flag.assigned_to = None
    flag.assigned_on = None
    flag.save(update_fields=["assigned_to", "assigned_on"])
    return flag
