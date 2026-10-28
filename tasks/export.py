from core.export import stamp, workbook_response

from .models import TaskUpdate


def _files(owner):
    return ", ".join(a.original_name for a in owner.attachments.all())


def tasks_workbook(tasks):
    """Every task in `tasks` with its updates, as a two-sheet download."""
    tasks = tasks.prefetch_related("attachments").order_by("due_date", "priority", "pk")
    task_rows = [
        (
            t.pk,
            t.assigned_to.display_name,
            t.assigned_by.display_name,
            t.priority,
            t.get_status_display(),
            t.description,
            t.received_at,
            t.due_date,
            t.closed_at,
            t.remind_at,
            t.get_remind_every_display(),
            _files(t),
        )
        for t in tasks
    ]
    updates = (
        TaskUpdate.objects.filter(task__in=tasks)
        .select_related("author")
        .prefetch_related("attachments")
        .order_by("task_id", "created_at")
    )
    update_rows = [
        (u.task_id, u.author.display_name, u.created_at, u.body, _files(u))
        for u in updates
    ]
    return workbook_response(
        stamp("tasks"),
        {
            "Tasks": (
                (
                    "Task #",
                    "Assigned to",
                    "Assigned by",
                    "Priority",
                    "Status",
                    "Report & job",
                    "Received",
                    "Due",
                    "Closed",
                    "Alarm",
                    "Alarm repeat",
                    "Files",
                ),
                task_rows,
            ),
            "Updates": (
                ("Task #", "Author", "Posted", "Update", "Files"),
                update_rows,
            ),
        },
    )
