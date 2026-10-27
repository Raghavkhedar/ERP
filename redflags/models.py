from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from tasks.models import IMAGE_EXTENSIONS


class Status(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


class RedFlag(models.Model):
    """A confidential report about a colleague. Only superadmins ever read it;
    see `services.can_read`.
    """

    # The names are kept as text too: a leaver's display name is anonymised, and
    # a flag has to stay readable after they go.
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    raised_by_name = models.CharField(max_length=150)
    raised_against = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    raised_against_name = models.CharField(max_length=150)
    raised_on = models.DateField(default=timezone.localdate, editable=False)
    incident_date = models.DateField()
    incident = models.TextField(max_length=4000)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="redflag_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(incident__regex=r"\S"), name="redflag_incident_not_blank"
            ),
            models.CheckConstraint(
                condition=~Q(raised_by=F("raised_against")),
                name="redflag_not_against_self",
            ),
        ]

    def __str__(self):
        return f"{self.raised_by_name} against {self.raised_against_name}"

    @property
    def summary(self):
        lines = self.incident.strip().splitlines()
        return lines[0] if lines else ""


class Note(models.Model):
    """A private note the superadmin keeps on a flag."""

    red_flag = models.ForeignKey(
        RedFlag, on_delete=models.PROTECT, related_name="notes"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    body = models.TextField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(body__regex=r"\S"), name="redflag_note_body_not_blank"
            ),
        ]

    def __str__(self):
        return f"{self.author}: {self.body[:40]}"


def attachment_path(attachment, filename):
    # A random name, as for feedback files: the real name is kept in original_name.
    suffix = Path(filename).suffix.lower()
    return f"redflags/{timezone.now():%Y/%m}/{uuid4().hex}{suffix}"


class Attachment(models.Model):
    """Evidence the raiser attached, such as a screenshot."""

    red_flag = models.ForeignKey(
        RedFlag, on_delete=models.PROTECT, related_name="attachments"
    )
    file = models.FileField(upload_to=attachment_path, max_length=200)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.original_name

    @property
    def is_image(self):
        return Path(self.original_name).suffix.lower() in IMAGE_EXTENSIONS
