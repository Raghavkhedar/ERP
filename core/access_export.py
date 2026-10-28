from core.access import MODULES
from core.export import stamp, workbook_response
from core.models import AccessGrant, Membership


def access_workbook(people):
    """Who works in which company, and which sections of which modules they hold.

    Same people as the Access page. Module and section names are the labels the
    page shows.
    """
    people = people.select_related("supervisor").prefetch_related("groups")
    ids = [p.pk for p in people]
    rows = [
        (
            p.username,
            p.display_name,
            p.supervisor.display_name if p.supervisor else "",
            ", ".join(
                label
                for label, on in (
                    ("Office admin", p.is_office_admin),
                    ("Trainer", p.is_trainer),
                )
                if on
            ),
        )
        for p in people
    ]
    memberships = (
        Membership.objects.filter(user__in=ids)
        .select_related("user", "company")
        .order_by("user__first_name", "user__username", "company__name")
    )
    grants = (
        AccessGrant.objects.filter(user__in=ids)
        .select_related("user", "company", "granted_by")
        .order_by("user__first_name", "user__username", "company__name", "module")
    )

    def label(grant):
        module = MODULES.get(grant.module)
        section = module.sections.get(grant.section) if module else None
        return (
            module.label if module else grant.module,
            section or grant.section,
        )

    return workbook_response(
        stamp("access"),
        {
            "People": (("Employee ID", "Name", "Supervisor", "Role"), rows),
            "Companies": (
                (
                    "Employee ID",
                    "Name",
                    "Company",
                    "Designation",
                    "Joined",
                    "Pays salary",
                ),
                [
                    (
                        m.user.username,
                        m.user.display_name,
                        m.company.name,
                        m.designation,
                        m.joined_on,
                        "Yes" if m.pays_salary else "No",
                    )
                    for m in memberships
                ],
            ),
            "Access": (
                (
                    "Employee ID",
                    "Name",
                    "Company",
                    "Module",
                    "Section",
                    "Granted by",
                    "Granted",
                ),
                [
                    (
                        g.user.username,
                        g.user.display_name,
                        g.company.name,
                        *label(g),
                        g.granted_by.display_name if g.granted_by else "",
                        g.created_at,
                    )
                    for g in grants
                ],
            ),
        },
    )
