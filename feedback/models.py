from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from tasks.models import IMAGE_EXTENSIONS


class Kind(models.TextChoices):
    PROBLEM = "problem", "Something went wrong"
    SUGGESTION = "suggestion", "An idea"
    PRAISE = "praise", "Something worked well"
    TRAINING_GAP = "training_gap", "I wasn't taught this"


class Area(models.TextChoices):
    """Where the feedback is about. The values are app names, so the form can
    guess the area from the page it was sent from. Add each new module here.
    """

    TASKS = "tasks", "Tasks"
    MEETINGS = "meetings", "Schedule"
    CHAT = "chat", "Chat"
    PLANS = "plans", "Daily plan"
    TRAINING = "training", "Training"
    OTHER = "other", "Something else"


class Status(models.TextChoices):
    NEW = "new", "New"
    DISCUSSING = "discussing", "Being discussed"
    RESOLVED = "resolved", "Resolved"


class Outcome(models.TextChoices):
    LESSON = "lesson", "Becomes a lesson"
    SOFTWARE_FIX = "software_fix", "Fixed in the software"
    NOTHING = "not_actionable", "Nothing to do"
    DUPLICATE = "duplicate", "Already reported"


class Feedback(models.Model):
    """What someone told us, from any page, and what came of it."""

    submitter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="feedback"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    area = models.CharField(max_length=20, choices=Area.choices)
    message = models.TextField(max_length=4000)
    page_url = models.CharField(
        max_length=300, blank=True, help_text="The page it was sent from."
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    outcome = models.CharField(
        max_length=20,
        choices=Outcome.choices,
        blank=True,
        help_text="What came of it. Needed before it can be resolved.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "feedback"
        indexes = [
            models.Index(
                fields=["submitter", "created_at"], name="feedback_submitter_idx"
            ),
            models.Index(fields=["status", "created_at"], name="feedback_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(message__regex=r"\S"),
                name="feedback_message_not_blank",
            ),
            models.CheckConstraint(
                condition=~Q(status="resolved") | ~Q(outcome=""),
                name="feedback_resolved_has_outcome",
            ),
        ]

    def __str__(self):
        return f"{self.submitter}: {self.summary}"

    @property
    def summary(self):
        lines = self.message.strip().splitlines()
        return lines[0] if lines else ""


class Comment(models.Model):
    """One message in a feedback item's discussion."""

    feedback = models.ForeignKey(
        Feedback, on_delete=models.CASCADE, related_name="comments"
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
                condition=Q(body__regex=r"\S"),
                name="feedback_comment_body_not_blank",
            ),
        ]

    def __str__(self):
        return f"{self.author}: {self.body[:40]}"


def attachment_path(attachment, filename):
    # A random name, as for task files: the real name is kept in original_name.
    suffix = Path(filename).suffix.lower()
    return f"feedback/{timezone.now():%Y/%m}/{uuid4().hex}{suffix}"


class Attachment(models.Model):
    """A file or screenshot on the feedback itself or on one of its comments."""

    feedback = models.ForeignKey(
        Feedback,
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,
        blank=True,
    )
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,
        blank=True,
    )
    file = models.FileField(upload_to=attachment_path, max_length=200)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(feedback__isnull=False, comment__isnull=True)
                | Q(feedback__isnull=True, comment__isnull=False),
                name="feedback_attachment_feedback_xor_comment",
            ),
        ]

    def __str__(self):
        return self.original_name

    @property
    def is_image(self):
        return Path(self.original_name).suffix.lower() in IMAGE_EXTENSIONS


class Lesson(models.Model):
    """What to teach, written up after feedback was discussed. This is what
    trainers read when they build a training module.
    """

    title = models.CharField(max_length=120)
    area = models.CharField(max_length=20, choices=Area.choices)
    what_happened = models.TextField(max_length=4000)
    why_it_happens = models.TextField(max_length=4000, blank=True)
    what_to_teach = models.TextField(max_length=4000)
    feedback = models.ManyToManyField(Feedback, related_name="lessons", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["area", "title", "id"]

    def __str__(self):
        return self.title
