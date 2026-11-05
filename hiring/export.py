from django.db.models import Count, Q

from core.export import stamp, workbook_response


def requisitions_workbook(requisitions):
    rows = [
        (
            r.pk,
            r.get_department_display(),
            r.profile,
            r.headcount,
            r.sourced_count,
            r.duplicate_count,
            r.site,
            r.needed_by,
            r.get_status_display(),
            r.opened_by.get_full_name() or r.opened_by.get_username(),
            r.company.name,
        )
        for r in requisitions.select_related("company", "opened_by")
    ]
    return workbook_response(
        stamp("requisitions"),
        {
            "Requisitions": (
                (
                    "Req #",
                    "Department",
                    "Profile",
                    "Headcount",
                    "Sourced",
                    "Duplicates",
                    "Site",
                    "Needed by",
                    "Status",
                    "Opened by",
                    "Company",
                ),
                rows,
            )
        },
    )


def sourced_workbook(rows):
    by_source = [
        (r["source"] or "(none)", r["total"], r["dups"], r["dups"] / r["total"])
        for r in rows.order_by()
        .values("source")
        .annotate(total=Count("id"), dups=Count("id", filter=Q(is_duplicate=True)))
        .order_by("source")
    ]
    return workbook_response(
        stamp("sourced-numbers"),
        {
            "Sourced numbers": (
                (
                    "Requisition",
                    "Name",
                    "Phone",
                    "Source",
                    "Result",
                    "Card #",
                    "Received",
                    "Sourced by",
                ),
                [
                    (
                        str(s.requisition),
                        s.person.name,
                        s.person.phone,
                        s.source,
                        "Duplicate" if s.is_duplicate else "New",
                        s.person_id,
                        s.created_at,
                        s.sourced_by.get_full_name() or s.sourced_by.get_username(),
                    )
                    for s in rows
                ],
            ),
            "By source": (
                ("Source", "Sourced", "Duplicates", "Duplicate rate"),
                by_source,
            ),
        },
    )
