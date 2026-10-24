from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.text import Truncator

from notifications.services import notify

from .models import Attachment, Comment, Feedback, Status


def admins():
    """Who reads and answers feedback: for now the Office admins."""
    return (
        get_user_model()
        .objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__name="Office admin"))
        .distinct()
    )


def is_reader(user):
    return user.is_office_admin


def visible_feedback(user):
    """Admins see all feedback; everyone else sees only what they sent."""
    items = Feedback.objects.select_related("submitter")
    return items if is_reader(user) else items.filter(submitter=user)


def can_view(user, feedback):
    return is_reader(user) or feedback.submitter_id == user.pk


def attach(files, **owner):
    for upload in files:
        Attachment.objects.create(
            file=upload, original_name=upload.name, size=upload.size, **owner
        )


def _link(feedback, fragment=""):
    return reverse("feedback:detail", args=[feedback.pk]) + fragment


@transaction.atomic
def submit(user, kind, area, message, page_url="", files=()):
    """Record feedback and tell the admins."""
    feedback = Feedback.objects.create(
        submitter=user,
        kind=kind,
        area=area,
        message=message,
        page_url=page_url[:300],
    )
    attach(files, feedback=feedback)
    text = f"{user.display_name} sent feedback: {Truncator(feedback.summary).chars(80)}"
    for admin in admins().exclude(pk=user.pk):
        notify(admin, text, _link(feedback))
    return feedback


@transaction.atomic
def add_comment(feedback, user, body, files=()):
    """Add to the discussion. The submitter and the admins who took part are
    told; an admin's first reply moves a new item to "being discussed".
    """
    if not can_view(user, feedback):
        raise PermissionDenied("This isn't your feedback.")
    comment = Comment.objects.create(feedback=feedback, author=user, body=body)
    attach(files, comment=comment)

    if is_reader(user) and feedback.status == Status.NEW:
        feedback.status = Status.DISCUSSING
        feedback.save(update_fields=["status"])

    people = {feedback.submitter}
    people.update(admins().filter(pk__in=feedback.comments.values("author")))
    if user.pk == feedback.submitter_id:
        people.update(admins())
    people.discard(user)
    summary = Truncator(feedback.summary).chars(60)
    text = f"{user.display_name} commented on feedback: {summary}"
    for person in people:
        notify(person, text, _link(feedback, f"#comment-{comment.pk}"))
    return comment
