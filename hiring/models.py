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


class FollowUp(models.Model):
    """A call (or later step) someone has to make for a candidate. Logging a call
    completes it and can open the next. Rescheduling keeps the original date."""

    class Purpose(models.TextChoices):
        CALL = "call", "Call"
        INTERVIEW = "interview", "Interview"
        OFFER = "offer", "Offer"
        JOINING = "joining", "Joining"
        ASSESSMENT = "assessment", "Assessment"
        UPDATE = "update", "Update"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        NOT_DONE = "not_done", "Not done"
        CANCELLED = "cancelled", "Cancelled"

    class Reason(models.TextChoices):
        SHORTAGE = "shortage", "Staff shortage"
        VOLUME = "volume", "High volume"
        HOLIDAY = "holiday", "Holiday"
        CANDIDATE = "candidate", "Candidate asked"
        OTHER = "other", "Other"
        MISTAKE = "mistake", "Mistake"

    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="followups"
    )
    requisition = models.ForeignKey(
        Requisition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="followups",
    )
    purpose = models.CharField(max_length=20, choices=Purpose, default=Purpose.CALL)
    due = models.DateTimeField()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="followups"
    )
    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING)
    notes = models.TextField(blank=True)
    original_due = models.DateTimeField(null=True, blank=True)
    reschedule_count = models.PositiveIntegerField(default=0)
    reschedule_reason = models.CharField(max_length=20, choices=Reason, blank=True)
    reassigned_from = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["due", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["person", "purpose"],
                condition=models.Q(status="pending"),
                name="one_pending_followup_per_person_purpose",
            )
        ]

    def __str__(self):
        return f"{self.get_purpose_display()} {self.person}"


class CallLog(models.Model):
    """One per call, written by the caller's outcome action."""

    class Outcome(models.TextChoices):
        INTERESTED = "interested", "Reached, interested"
        CALL_BACK = "call_back", "Asked to call back"
        NO_ANSWER = "no_answer", "No answer"
        INTERVIEW = "interview", "Interview booked"
        NOT_INTERESTED = "not_interested", "Not interested"
        DO_NOT_CALL = "do_not_call", "Do not call"

    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="calls"
    )
    followup = models.ForeignKey(
        FollowUp, null=True, blank=True, on_delete=models.PROTECT, related_name="calls"
    )
    caller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    called_at = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=20, choices=Outcome)
    notes = models.TextField(blank=True)
    # Bulk shifts and on-demand moves migrated from Zoho aren't real calls.
    not_a_call = models.BooleanField(default=False)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-called_at", "-id"]

    def __str__(self):
        return f"{self.get_outcome_display()} {self.person}"
