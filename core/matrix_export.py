from core.access import MODULES
from core.export import stamp, workbook_response
from core.models import AccessLog


def _tabs():
    # shortcut: tab names alone as headers, prefix the module once a second joins
    return [
        (key, tab, label)
        for key, module in MODULES.items()
        if module.in_matrix
        for tab, label in module.sections.items()
    ]


def matrix_workbook(company, rows):
    """The grid as a spreadsheet: one row per person, Yes where they hold a tab."""
    tabs = _tabs()
    return workbook_response(
        stamp(f"access-matrix-{company.slug}"),
        {
            "Matrix": (
                ["Employee ID", "Name", *[label for _, _, label in tabs]],
                [
                    [
                        r["user"].username,
                        r["user"].display_name,
                        *["Yes" if (m, t) in r["held"] else "" for m, t, _ in tabs],
                    ]
                    for r in rows
                ],
            )
        },
    )


def history_workbook(company, logs):
    """Every access change for one company, newest first."""
    labels = {(m, t): label for m, t, label in _tabs()}
    names = {key: m.label for key, m in MODULES.items()}
    return workbook_response(
        stamp(f"access-history-{company.slug}"),
        {
            "History": (
                ["When", "Who", "Whom", "Module", "Tab", "What", "Note"],
                [
                    [
                        e.created_at,
                        e.actor_name,
                        e.subject_name,
                        names.get(e.module, e.module),
                        labels.get((e.module, e.section), e.section),
                        AccessLog.Action(e.action).label,
                        e.note,
                    ]
                    for e in logs
                ],
            )
        },
    )
