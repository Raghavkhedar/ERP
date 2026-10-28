from core.export import stamp, workbook_response

from .models import Note


def red_flags_workbook(flags):
    """Flags with their notes. The names are the ones stored on the flag, so a
    leaver's flag still reads properly.
    """
    flags = flags.select_related("assigned_to").prefetch_related("attachments")
    rows = [
        (
            f.pk,
            f.raised_on,
            f.raised_by_name,
            f.raised_against_name,
            f.incident_date,
            f.incident,
            f.get_status_display(),
            f.assigned_to.display_name if f.assigned_to else "",
            f.assigned_on,
            ", ".join(a.original_name for a in f.attachments.all()),
        )
        for f in flags
    ]
    notes = (
        Note.objects.filter(red_flag__in=flags)
        .select_related("author")
        .order_by("red_flag_id", "created_at", "id")
    )
    return workbook_response(
        stamp("red-flags"),
        {
            "Red flags": (
                (
                    "Flag #",
                    "Raised on",
                    "Raised by",
                    "Raised against",
                    "Incident date",
                    "Incident",
                    "Status",
                    "Assigned to",
                    "Assigned on",
                    "Files",
                ),
                rows,
            ),
            "Notes": (
                ("Flag #", "Author", "Written", "Note"),
                [
                    (n.red_flag_id, n.author.display_name, n.created_at, n.body)
                    for n in notes
                ],
            ),
        },
    )
