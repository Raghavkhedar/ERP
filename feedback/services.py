from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator

from notifications.services import notify

from .models import Attachment, Comment, Feedback, Lesson, Outcome, Status

READER_GROUPS = ("Office admin", "Trainer")


def readers():
    """Who reads and answers feedback and writes lessons: the Office admins
    and the trainers. This and `is_reader` are the only places that decide it.
    """
    return (
        get_user_model()
        .objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__name__in=READER_GROUPS))
        .distinct()
    )


def is_reader(user):
    return user.is_office_admin or user.is_trainer


def visible_feedback(user):
    """Admins and trainers see all feedback; everyone else sees only what they
    sent and what a superadmin assigned to them.
    """
    items = Feedback.objects.select_related("submitter")
    if is_reader(user):
        return items
    return items.filter(Q(submitter=user) | Q(assigned_to=user))


def can_view(user, feedback):
    return (
        is_reader(user)
        or feedback.submitter_id == user.pk
        or feedback.assigned_to_id == user.pk
    )


def attach(files, **owner):
    for upload in files:
        Attachment.objects.create(
            file=upload, original_name=upload.name, size=upload.size, **owner
        )


def _link(feedback, fragment=""):
    return reverse("feedback:detail", args=[feedback.pk]) + fragment


@transaction.atomic
def submit(user, kind, area, message, page_url="", files=()):
    """Record feedback and tell the admins and trainers."""
    feedback = Feedback.objects.create(
        submitter=user,
        kind=kind,
        area=area,
        message=message,
        page_url=page_url[:300],
    )
    attach(files, feedback=feedback)
    text = f"{user.display_name} sent feedback: {Truncator(feedback.summary).chars(80)}"
    for reader in readers().exclude(pk=user.pk):
        notify(reader, text, _link(feedback))
    return feedback


@transaction.atomic
def add_comment(feedback, user, body, files=()):
    """Add to the discussion. The submitter and the admins and trainers who
    took part are told; a reader's first reply moves a new item to "being
    discussed".
    """
    if not can_view(user, feedback):
        raise PermissionDenied("This isn't your feedback.")
    comment = Comment.objects.create(feedback=feedback, author=user, body=body)
    attach(files, comment=comment)

    if is_reader(user) and feedback.status == Status.NEW:
        feedback.status = Status.DISCUSSING
        feedback.save(update_fields=["status"])

    people = {feedback.submitter}
    if feedback.assigned_to:
        people.add(feedback.assigned_to)
    people.update(readers().filter(pk__in=feedback.comments.values("author")))
    if user.pk == feedback.submitter_id:
        people.update(readers())
    people.discard(user)
    summary = Truncator(feedback.summary).chars(60)
    text = f"{user.display_name} commented on feedback: {summary}"
    for person in people:
        notify(person, text, _link(feedback, f"#comment-{comment.pk}"))
    return comment


class FeedbackError(Exception):
    """A change that can't be made; the message is shown to the person."""


@transaction.atomic
def set_resolution(feedback, user, status, outcome):
    """Move feedback along and record what came of it. Only readers do this;
    the submitter is told when it is resolved.
    """
    if not is_reader(user):
        raise PermissionDenied("Only admins and trainers change feedback status.")
    if status not in Status.values or outcome not in ["", *Outcome.values]:
        raise FeedbackError("That isn't a status or outcome.")
    if status == Status.RESOLVED and not outcome:
        raise FeedbackError("Choose what came of it before resolving.")
    was_resolved = feedback.status == Status.RESOLVED
    feedback.status = status
    feedback.outcome = outcome
    feedback.save(update_fields=["status", "outcome"])
    if status == Status.RESOLVED and not was_resolved and feedback.submitter != user:
        result = Outcome(outcome).label.lower()
        summary = Truncator(feedback.summary).chars(60)
        notify(
            feedback.submitter,
            f"Your feedback was resolved ({result}): {summary}",
            _link(feedback),
        )
    return feedback


def supervisor_of_submitter(feedback):
    supervisor = feedback.submitter.supervisor
    return supervisor if supervisor and supervisor.is_active else None


@transaction.atomic
def assign_to_supervisor(feedback, user):
    """Hand the thread to the submitter's supervisor, who can read and reply."""
    if not (user.is_active and user.is_superuser):
        raise PermissionDenied("Only superadmins assign feedback.")
    supervisor = supervisor_of_submitter(feedback)
    if supervisor is None:
        raise FeedbackError(f"{feedback.submitter.display_name} has no supervisor set.")
    feedback.assigned_to = supervisor
    feedback.assigned_on = timezone.localdate()
    feedback.save(update_fields=["assigned_to", "assigned_on"])
    summary = Truncator(feedback.summary).chars(60)
    notify(supervisor, f"Feedback was assigned to you: {summary}", _link(feedback))
    return feedback


@transaction.atomic
def unassign(feedback, user):
    if not (user.is_active and user.is_superuser):
        raise PermissionDenied("Only superadmins assign feedback.")
    feedback.assigned_to = None
    feedback.assigned_on = None
    feedback.save(update_fields=["assigned_to", "assigned_on"])
    return feedback


@transaction.atomic
def save_lesson(form, user):
    """Save a lesson form. Feedback it is written from becomes a lesson outcome."""
    if not is_reader(user):
        raise PermissionDenied("Only admins and trainers write lessons.")
    lesson = form.save(commit=False)
    if lesson.pk is None:
        lesson.created_by = user
    lesson.save()
    form.save_m2m()
    lesson.feedback.filter(outcome="").update(outcome=Outcome.LESSON)
    return lesson


def search_lessons(query="", area=""):
    lessons = Lesson.objects.all()
    if area:
        lessons = lessons.filter(area=area)
    for word in query.split():
        lessons = lessons.filter(
            Q(title__icontains=word)
            | Q(what_happened__icontains=word)
            | Q(why_it_happens__icontains=word)
            | Q(what_to_teach__icontains=word)
        )
    return lessons
