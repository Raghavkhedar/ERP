from core.export import stamp, workbook_response

from .models import Comment, Lesson


def _files(owner):
    return ", ".join(a.original_name for a in owner.attachments.all())


def feedback_workbook(items, with_lessons=False):
    """Feedback with its discussion, plus the lessons when the reader may see them."""
    items = items.select_related("assigned_to").prefetch_related(
        "attachments", "lessons"
    )
    rows = [
        (
            f.pk,
            f.created_at,
            f.submitter.display_name,
            f.get_kind_display(),
            f.get_area_display(),
            f.message,
            f.page_url,
            f.get_status_display(),
            f.get_outcome_display(),
            f.assigned_to.display_name if f.assigned_to else "",
            ", ".join(lesson.title for lesson in f.lessons.all()),
            _files(f),
        )
        for f in items
    ]
    comments = (
        Comment.objects.filter(feedback__in=items)
        .select_related("author")
        .prefetch_related("attachments")
        .order_by("feedback_id", "created_at", "id")
    )
    sheets = {
        "Feedback": (
            (
                "Feedback #",
                "Sent",
                "From",
                "Kind",
                "About",
                "Message",
                "Page",
                "Status",
                "Outcome",
                "Assigned to",
                "Lessons",
                "Files",
            ),
            rows,
        ),
        "Comments": (
            ("Feedback #", "Author", "Posted", "Comment", "Files"),
            [
                (c.feedback_id, c.author.display_name, c.created_at, c.body, _files(c))
                for c in comments
            ],
        ),
    }
    if with_lessons:
        lessons = Lesson.objects.select_related("created_by").prefetch_related(
            "feedback"
        )
        sheets["Lessons"] = (
            (
                "Title",
                "About",
                "What happened",
                "Why it happens",
                "What to teach",
                "Feedback #",
                "Written by",
                "Written",
            ),
            [
                (
                    lesson.title,
                    lesson.get_area_display(),
                    lesson.what_happened,
                    lesson.why_it_happens,
                    lesson.what_to_teach,
                    ", ".join(str(f.pk) for f in lesson.feedback.all()),
                    lesson.created_by.display_name,
                    lesson.created_at,
                )
                for lesson in lessons
            ],
        )
    return workbook_response(stamp("feedback"), sheets)
