from django.conf import settings
from django.db import models
from django.db.models import F, Q
from simple_history.models import HistoricalRecords


class Meeting(models.Model):
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organized_meetings",
    )
    title = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    note = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["starts_at", "id"]
        indexes = [
            models.Index(fields=["starts_at"], name="meetings_starts_at_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="meetings_ends_after_start",
            ),
            models.CheckConstraint(
                condition=Q(title__regex=r"\S"),
                name="meetings_title_not_blank",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.starts_at:%d %b %H:%M})"

    @property
    def is_cancelled(self):
        return self.cancelled_at is not None


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"


class Invitation(models.Model):
    meeting = models.ForeignKey(
        Meeting, on_delete=models.PROTECT, related_name="invitations"
    )
    invitee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="meeting_invitations",
    )
    status = models.CharField(
        max_length=10,
        choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING,
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "invitee"], name="meetings_unique_invitation"
            ),
            models.CheckConstraint(
                condition=Q(status__in=InvitationStatus.values),
                name="meetings_invitation_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(status=InvitationStatus.PENDING, responded_at__isnull=True)
                | (~Q(status=InvitationStatus.PENDING) & Q(responded_at__isnull=False)),
                name="meetings_responded_at_matches_status",
            ),
        ]

    def __str__(self):
        return f"{self.invitee} to {self.meeting.title}: {self.status}"
