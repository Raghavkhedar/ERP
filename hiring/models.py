from datetime import datetime, time
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords


def day_start(day):
    """Follow-ups are dated, not timed: a date is kept as the start of that day."""
    return timezone.make_aware(datetime.combine(day, time.min))


def interview_file_path(interview, filename):
    # A random name, as for red-flag files; they are served only through a view.
    suffix = Path(filename).suffix.lower()
    return f"interviews/{timezone.now():%Y/%m}/{uuid4().hex}{suffix}"


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

    class Kind(models.TextChoices):
        NEW = "new", "New"
        BACKFILL = "backfill", "Backfill"

    class Employment(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        TEMPORARY = "temporary", "Temporary"
        PART_TIME = "part_time", "Part-time"

    # Sourcing goes to the highest first: fire fighting, then urgent.
    class Urgency(models.TextChoices):
        FIRE_FIGHTING = "fire_fighting", "Fire fighting"
        URGENT = "urgent", "Urgent"
        NOT_URGENT = "not_urgent", "Not urgent"

    class Exposure(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class Gender(models.TextChoices):
        ANY = "", "No restriction"
        MALE = "M", "Male"
        FEMALE = "F", "Female"

    company = models.ForeignKey(
        "core.Company", on_delete=models.PROTECT, related_name="requisitions"
    )
    kind = models.CharField(max_length=10, choices=Kind, default=Kind.NEW)
    department = models.CharField(max_length=20, choices=Department)
    sub_department = models.CharField(max_length=120, blank=True)
    # The designation.
    profile = models.CharField(max_length=120)
    headcount = models.PositiveIntegerField()
    site = models.CharField(max_length=200, blank=True)
    needed_by = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status, default=Status.OPEN)
    urgency = models.CharField(
        max_length=15, choices=Urgency, default=Urgency.NOT_URGENT
    )
    experience_years = models.CharField(max_length=40, blank=True)
    employment = models.CharField(
        max_length=10, choices=Employment, default=Employment.PERMANENT
    )
    gender = models.CharField(max_length=1, choices=Gender, blank=True)
    requirements = models.TextField(blank=True)
    languages = models.JSONField(default=list, blank=True)
    industry = models.CharField(max_length=200, blank=True)
    education = models.CharField(max_length=200, blank=True)
    previous_employment_restriction = models.CharField(max_length=200, blank=True)
    reputed_company_must = models.BooleanField(default=False)
    exposure = models.CharField(max_length=10, choices=Exposure, blank=True)
    budget = models.CharField(max_length=100, blank=True)
    physical_restriction = models.CharField(max_length=200, blank=True)
    domicile_restriction = models.CharField(max_length=200, blank=True)
    age_restriction = models.CharField(max_length=100, blank=True)
    other_details = models.TextField(blank=True)
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


class RequisitionPost(models.Model):
    """One entry in a requisition's discussion: a comment, or a job post's details
    (portal, keyword, date, status, payment). Comments are append-only, like a
    chat; job post details can be edited."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        CLOSED = "closed", "Closed"

    class Payment(models.TextChoices):
        FREE = "free", "Free"
        PAID = "paid", "Paid"

    requisition = models.ForeignKey(
        Requisition, on_delete=models.CASCADE, related_name="posts"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    body = models.TextField(max_length=4000, blank=True)
    # Job post details; portal set means this entry is a job post.
    portal = models.CharField(max_length=120, blank=True)
    keyword = models.CharField(max_length=200, blank=True)
    posted_on = models.DateField(null=True, blank=True)
    post_status = models.CharField(max_length=10, choices=Status, blank=True)
    payment = models.CharField(max_length=10, choices=Payment, blank=True)
    portal_user = models.CharField(max_length=200, blank=True)
    posting_company = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Job post details can be edited (e.g. status), so every change is kept.
    history = HistoricalRecords()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(body="") | ~models.Q(portal=""),
                name="requisition_post_not_empty",
            )
        ]

    def __str__(self):
        return f"{self.requisition_id}: {self.portal or self.body[:40]}"

    @property
    def is_job_post(self):
        return bool(self.portal)


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
        CALL = "call", "Normal follow-up"
        INTERVIEW = "interview", "Interview"
        OFFER = "offer", "Offer"
        JOINING = "joining", "Joining"
        UPDATE = "update", "Update"
        RESCHEDULE = "reschedule", "Reschedule"
        ASSESSMENT = "assessment", "Assessment update"
        OTHER = "other", "Other"

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
    # What the caller typed when the intention is "Other".
    purpose_other = models.CharField(max_length=200, blank=True)
    due = models.DateTimeField()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="followups"
    )
    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING)
    notes = models.TextField(blank=True)
    original_due = models.DateTimeField(null=True, blank=True)
    reschedule_count = models.PositiveIntegerField(default=0)
    reschedule_reason = models.CharField(max_length=20, choices=Reason, blank=True)
    # The call alarm stays quiet until then; set by "10 min" / "1 hour" / "Tomorrow".
    snoozed_until = models.DateTimeField(null=True, blank=True)
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
        indexes = [
            models.Index(
                fields=["owner", "status", "due"], name="followup_owner_status_due"
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["person", "purpose"],
                condition=models.Q(status="pending"),
                name="one_pending_followup_per_person_purpose",
            )
        ]

    def __str__(self):
        return f"{self.get_purpose_display()} {self.person}"

    @property
    def intention(self):
        return self.purpose_other or self.get_purpose_display()


class CallLog(models.Model):
    """One per call, written by the caller's outcome action."""

    # The tags the recruiters use; they only label the call.
    class Outcome(models.TextChoices):
        REG_TOUCH = "reg_touch", "Reg Call Touch"
        REG_NOT_TOUCH = "reg_not_touch", "Reg Call Not Touch"
        REG_NOT_ATTENDED = "reg_not_attended", "Reg Call Not Attended"
        REG_FF = "reg_ff", "Reg F-F Interview"
        REG_T = "reg_t", "Reg T Interview"
        WA_TOUCH = "wa_touch", "WA Call Touch"
        WA_TOUCH_DR = "wa_touch_dr", "WA Call Touch - DR"
        WA_NOT_TOUCH = "wa_not_touch", "WA Call Not Touch"
        WA_NOT_ATTENDED = "wa_not_attended", "WA Call Not Attended"
        WA_FF = "wa_ff", "WA F-F Interview"
        WA_T = "wa_t", "WA T Interview"
        UPDATE_TOUCH = "update_touch", "Update Touch"
        UPDATE_NOT_TOUCH = "update_not_touch", "Update Not Touch"
        BLANK = "blank", "Blank"
        CALL = "call", "call"

    class Kind(models.TextChoices):
        OUTBOUND = "outbound", "Outbound"
        INBOUND = "inbound", "Inbound"

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
    # The caller's written status of the call.
    notes = models.TextField(blank=True)
    call_type = models.CharField(max_length=10, choices=Kind, default=Kind.OUTBOUND)
    # The candidate moved their interview; kept apart from normal calls to track it.
    rescheduled = models.BooleanField(default=False)
    reschedule_reason = models.TextField(blank=True)
    department_changed = models.BooleanField(default=False)
    discussed = models.BooleanField(default=False)
    # Answers of the whereabout forms (see whereabouts.py); empty when not filled.
    mini_whereabout = models.JSONField(default=dict, blank=True)
    major_whereabout = models.JSONField(default=dict, blank=True)
    # Bulk shifts and on-demand moves imported from the old system aren't real calls.
    not_a_call = models.BooleanField(default=False)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-called_at", "-id"]

    def __str__(self):
        return f"{self.get_outcome_display()} {self.person}"


class Interview(models.Model):
    """The interview event, pre-filled from the follow-up that booked it."""

    class Result(models.TextChoices):
        PENDING = "pending", "Waiting for HR"
        SELECTED = "selected", "Selected"
        HOLD = "hold", "Hold"
        REJECTED = "rejected", "Rejected"

    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="interviews"
    )
    requisition = models.ForeignKey(
        Requisition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="interviews",
    )
    followup = models.OneToOneField(
        FollowUp, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    scheduled_at = models.DateTimeField()
    result = models.CharField(max_length=20, choices=Result)
    questions = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    profile = models.CharField(max_length=40, blank=True)
    # The form's answers, education and vehicle rows; see interview_form.py.
    answers = models.JSONField(default=dict, blank=True)
    photo = models.FileField(upload_to=interview_file_path, max_length=200, blank=True)
    resume = models.FileField(upload_to=interview_file_path, max_length=200, blank=True)
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-scheduled_at", "-id"]

    def __str__(self):
        return f"{self.person} · {self.get_result_display()}"


class HRAssessment(models.Model):
    """HR's view of an interview, kept apart from it and readable only by those
    granted the HR assessments section."""

    class Level(models.TextChoices):
        EXPERT = "expert", "Expert"
        INTERMEDIATE = "intermediate", "Intermediate"
        BEGINNER = "beginner", "Beginner"
        HELPER = "helper", "Helper"

    interview = models.OneToOneField(
        Interview, on_delete=models.PROTECT, related_name="hr"
    )
    decision = models.CharField(max_length=20, choices=Interview.Result)
    level = models.CharField(max_length=20, choices=Level, blank=True)
    hold_tenure = models.CharField(max_length=60, blank=True)
    comments = models.TextField(blank=True)
    answers = models.JSONField(default=dict, blank=True)
    assessor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    def __str__(self):
        return f"HR: {self.interview}"


class Offer(models.Model):
    """The offer made to one candidate. Negotiation is a list of rounds; the
    offer ends as accepted (with a joining date) or declined."""

    class State(models.TextChoices):
        OFFERED = "offered", "Offered"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="offers"
    )
    requisition = models.ForeignKey(
        Requisition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="offers",
    )
    state = models.CharField(max_length=20, choices=State, default=State.OFFERED)
    joining_date = models.DateField(null=True, blank=True)
    # The day they actually turned up, as opposed to the promised joining_date.
    joined_on = models.DateField(null=True, blank=True)
    # Filled in when they join: what they were given, and whether they got a SIM.
    resources = models.TextField(blank=True)
    sim_allotted = models.CharField(
        max_length=3, choices=[("Yes", "Yes"), ("No", "No")], blank=True
    )
    onboarding_notes = models.TextField(blank=True)
    decline_reason = models.CharField(max_length=200, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    made_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["state", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["person"],
                condition=models.Q(state="offered"),
                name="one_open_offer_per_person",
            ),
            models.CheckConstraint(
                condition=~models.Q(state="accepted")
                | models.Q(joining_date__isnull=False),
                name="accepted_offer_has_joining_date",
            ),
            models.CheckConstraint(
                condition=models.Q(joined_on__isnull=True) | models.Q(state="accepted"),
                name="only_accepted_offers_join",
            ),
        ]

    def __str__(self):
        return f"{self.person} · {self.get_state_display()}"

    @property
    def latest(self):
        # Reads the prefetched rounds when the list was loaded with them.
        return max(self.rounds.all(), key=lambda r: r.id, default=None)


class OfferRound(models.Model):
    """One step of the negotiation: what we offered and what they asked for."""

    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name="rounds")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    counter = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    note = models.CharField(max_length=300, blank=True)
    by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="offer_round_amount_gt_0"
            )
        ]

    def __str__(self):
        return f"{self.offer.person}: {self.amount}"
