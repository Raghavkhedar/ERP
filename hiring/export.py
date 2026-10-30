from core.export import stamp, workbook_response


def requisitions_workbook(requisitions):
    rows = [
        (
            r.pk,
            r.get_department_display(),
            r.profile,
            r.headcount,
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
