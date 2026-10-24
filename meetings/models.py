from django.conf import settings
from django.db import models
from django.db.models import F, Q
from simple_history.models import HistoricalRecords


class Slot(models.Model):
    """A time someone is free to meet; another person may book it."""

    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="hosted_slots",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="booked_slots",
    )
    topic = models.CharField(max_length=200, blank=True)
    booked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When both people were reminded that the meeting is about to start.",
    )
    block_reason = models.CharField(
        max_length=200,
        blank=True,
        help_text="Why the host blocked this time. Only the host sees it.",
    )
    office_hours = models.BooleanField(
        default=False, help_text="Opened automatically for the person's office hours."
    )

    history = HistoricalRecords(excluded_fields=["reminded_at"])

    class Meta:
        ordering = ["starts_at", "id"]
        indexes = [
            models.Index(fields=["host", "starts_at"], name="meetings_host_start_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="meetings_slot_ends_after_start",
            ),
            models.CheckConstraint(
                condition=Q(booked_by__isnull=True) | ~Q(booked_by=F("host")),
                name="meetings_slot_not_booked_by_host",
            ),
            models.CheckConstraint(
                condition=Q(booked_by__isnull=True, booked_at__isnull=True, topic="")
                | (
                    Q(booked_by__isnull=False, booked_at__isnull=False)
                    & Q(topic__regex=r"\S")
                ),
                name="meetings_slot_booking_complete",
            ),
        ]

    def __str__(self):
        return f"{self.host} {self.starts_at:%d %b %H:%M}"

    @property
    def is_booked(self):
        return self.booked_by_id is not None

    @property
    def is_cancelled(self):
        return self.cancelled_at is not None


class Conference(models.Model):
    """A group event the host invites people to; invitees accept or decline."""

    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="hosted_conferences",
    )
    title = models.CharField(max_length=200)
    agenda = models.TextField(blank=True)
    location = models.CharField(
        max_length=200, blank=True, help_text="A room, or a link to the call."
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once the host and attendees were reminded.",
    )

    history = HistoricalRecords(excluded_fields=["reminded_at"])

    class Meta:
        ordering = ["starts_at", "id"]
        indexes = [
            models.Index(fields=["starts_at"], name="meetings_conf_start_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="meetings_conference_ends_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.title} {self.starts_at:%d %b %H:%M}"

    @property
    def is_cancelled(self):
        return self.cancelled_at is not None


class Invitation(models.Model):
    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    conference = models.ForeignKey(
        Conference, on_delete=models.CASCADE, related_name="invitations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="conference_invitations",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.INVITED
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conference", "user"], name="meetings_invitation_once"
            ),
        ]

    def __str__(self):
        return f"{self.user} {self.status} {self.conference_id}"
