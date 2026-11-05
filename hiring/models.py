from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class Requisition(models.Model):
    """A request for people, e.g. three MECH fitters for a site by a date.
    Sourced, screened and joined counts are worked out when shown, never stored."""

    class Department(models.TextChoices):
        BO = "bo", "BO"
        TRAINING = "training", "Training"
        HR = "hr", "HR"
        SALES = "sales", "Sales"
        OPERATIONS = "operations", "Operations"
        OTHERS = "others", "Others"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    company = models.ForeignKey(
        "core.Company", on_delete=models.PROTECT, related_name="requisitions"
    )
    department = models.CharField(max_length=20, choices=Department)
    profile = models.CharField(max_length=120)
    headcount = models.PositiveIntegerField()
    site = models.CharField(max_length=200, blank=True)
    needed_by = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status, default=Status.OPEN)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # Bumped on every save; a form carrying an older number is rejected.
    version = models.PositiveIntegerField(default=1)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["status", "needed_by", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(headcount__gte=1), name="requisition_headcount_gte_1"
            )
        ]

    def __str__(self):
        return f"{self.headcount} × {self.profile}"


class SourcedNumber(models.Model):
    """One row per number received, for one requisition. A number that matches an
    existing card creates no second card: the row points at that card and is
    marked a duplicate. Never blocked, never merged."""

    requisition = models.ForeignKey(
        Requisition, on_delete=models.PROTECT, related_name="sourced"
    )
    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="sourced"
    )
    source = models.CharField(max_length=120, blank=True)
    is_duplicate = models.BooleanField(default=False)
    sourced_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.person} for {self.requisition}"
