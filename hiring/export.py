from django.db.models import Count, Q

from core.export import stamp, workbook_response

from .models import CallLog, OfferRound


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


def followups_workbook(followups):
    people = {f.person_id for f in followups}
    return workbook_response(
        stamp("follow-ups"),
        {
            "Follow-ups": (
                (
                    "Candidate",
                    "Phone",
                    "Purpose",
                    "Due",
                    "Owner",
                    "Requisition",
                    "Rescheduled",
                    "Original due",
                ),
                [
                    (
                        f.person.name,
                        f.person.phone,
                        f.get_purpose_display(),
                        f.due,
                        f.owner.get_full_name() or f.owner.get_username(),
                        str(f.requisition) if f.requisition else "",
                        f.reschedule_count,
                        f.original_due,
                    )
                    for f in followups
                ],
            ),
            "Call log": (
                ("Candidate", "When", "Caller", "Outcome", "Notes"),
                [
                    (
                        c.person.name,
                        c.called_at,
                        c.caller.get_full_name() or c.caller.get_username(),
                        c.get_outcome_display(),
                        c.notes,
                    )
                    for c in CallLog.objects.filter(person_id__in=people)
                    .exclude(not_a_call=True)
                    .select_related("person", "caller")
                ],
            ),
        },
    )


def interviews_workbook(interviews, include_hr=False):
    def who(u):
        return u.get_full_name() or u.get_username()

    sheets = {
        "Interviews": (
            (
                "Candidate",
                "Phone",
                "Requisition",
                "Interview",
                "Result",
                "Interviewer",
                "Questions asked",
                "Notes",
            ),
            [
                (
                    i.person.name,
                    i.person.phone,
                    str(i.requisition) if i.requisition else "",
                    i.scheduled_at,
                    i.get_result_display(),
                    who(i.interviewer),
                    i.questions,
                    i.notes,
                )
                for i in interviews
            ],
        )
    }
    if include_hr:
        sheets["HR assessments"] = (
            ("Candidate", "Decision", "Level", "Hold tenure", "Comments", "Assessor"),
            [
                (
                    i.person.name,
                    i.hr.get_decision_display(),
                    i.hr.get_level_display(),
                    i.hr.hold_tenure,
                    i.hr.comments,
                    who(i.hr.assessor),
                )
                for i in interviews
                if hasattr(i, "hr")
            ],
        )
    return workbook_response(stamp("interviews"), sheets)


def offers_workbook(offers):
    def who(u):
        return u.get_full_name() or u.get_username()

    rounds = OfferRound.objects.filter(offer__in=offers).select_related(
        "offer__person", "by"
    )
    return workbook_response(
        stamp("offers"),
        {
            "Offers": (
                (
                    "Candidate",
                    "Phone",
                    "Requisition",
                    "State",
                    "Latest offer",
                    "Joining date",
                    "Decline reason",
                    "Made by",
                ),
                [
                    (
                        o.person.name,
                        o.person.phone,
                        str(o.requisition) if o.requisition else "",
                        o.get_state_display(),
                        float(o.latest.amount),
                        o.joining_date,
                        o.decline_reason,
                        who(o.made_by),
                    )
                    for o in offers
                ],
            ),
            "Rounds": (
                ("Candidate", "When", "We offered", "They asked", "Note", "By"),
                [
                    (
                        r.offer.person.name,
                        r.created_at,
                        float(r.amount),
                        float(r.counter) if r.counter else None,
                        r.note,
                        who(r.by),
                    )
                    for r in rounds
                ],
            ),
        },
    )


def onboarding_workbook(expecting, joined):
    def row(o):
        return (
            o.person.name,
            o.person.phone,
            str(o.requisition) if o.requisition else "",
            o.joining_date,
            o.joined_on,
            float(o.latest.amount),
        )

    return workbook_response(
        stamp("onboarding"),
        {
            "On-Boarding": (
                (
                    "Candidate",
                    "Phone",
                    "Requisition",
                    "Joining date",
                    "Joined on",
                    "Agreed offer",
                ),
                [row(o) for o in [*expecting, *joined]],
            )
        },
    )


STEPS = (
    ("Sourced", "sourced_n"),
    ("Duplicates", "duplicate_n"),
    ("Called", "called_n"),
    ("Interviewed", "interviewed_n"),
    ("Selected", "selected_n"),
    ("Offered", "offered_n"),
    ("Accepted", "accepted_n"),
    ("Joined", "joined_n"),
)


def funnel_workbook(requisitions):
    return workbook_response(
        stamp("funnel"),
        {
            "Funnel": (
                ("Requisition", "Site", "Status", "Needed", *(h for h, _ in STEPS)),
                [
                    (
                        str(r),
                        r.site,
                        r.get_status_display(),
                        r.headcount,
                        *(getattr(r, f) for _, f in STEPS),
                    )
                    for r in requisitions
                ],
            )
        },
    )
