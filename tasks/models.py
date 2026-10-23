from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

PRIORITIES = range(1, 21)  # 1 is the most urgent


class Status(models.TextChoices):
    OPEN = "open", "Open"
    ONGOING = "ongoing", "On-going"
    DONE = "done", "Done"
    CLOSED = "closed", "Closed"


class Task(models.Model):
    """Work an admin gives someone, from the day it's received until it's closed."""

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tasks"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    received_at = models.DateTimeField(
        "report/job received", default=timezone.now, editable=False
    )
    priority = models.PositiveSmallIntegerField(help_text="1 is the most urgent.")
    description = models.TextField("report & job", max_length=4000)
    due_date = models.DateField("completion date")
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["priority", "due_date", "id"]
        indexes = [
            models.Index(
                fields=["assigned_to", "status"], name="tasks_assignee_status_idx"
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(priority__gte=PRIORITIES[0], priority__lte=PRIORITIES[-1]),
                name="tasks_task_priority_range",
            ),
            models.CheckConstraint(
                condition=Q(description__regex=r"\S"),
                name="tasks_task_description_not_blank",
            ),
            models.CheckConstraint(
                condition=Q(status__in=Status.values),
                name="tasks_task_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(status=Status.CLOSED, closed_at__isnull=False)
                | (~Q(status=Status.CLOSED) & Q(closed_at__isnull=True)),
                name="tasks_task_closed_at_matches_status",
            ),
        ]

    def __str__(self):
        return f"P{self.priority} {self.title}"

    @property
    def title(self):
        """The description's first line, short enough for a list or timeline."""
        lines = self.description.strip().splitlines()
        line = lines[0] if lines else ""
        return line if len(line) <= 80 else line[:79].rstrip() + "…"

    @property
    def is_closed(self):
        return self.status == Status.CLOSED

    @property
    def is_overdue(self):
        return self.status in (Status.OPEN, Status.ONGOING) and (
            self.due_date < timezone.localdate()
        )
