import io
from datetime import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from plans.excel import schedule_rows
from plans.models import DailyPlan
from plans.services import PlanError

G, W = "goal", "work"


def sheet(*rows):
    book = Workbook()
    for row in rows:
        book.active.append(list(row))
    out = io.BytesIO()
    book.save(out)
    return SimpleUploadedFile("plan.xlsx", out.getvalue())


def test_header_with_start_and_end_columns():
    rows = schedule_rows(
        sheet(
            ("Start", "End", "Task"),
            (time(9, 30), time(11), "Call suppliers"),
            ("11:00", "12:30", "Vendor report"),
        )
    )
    assert rows == [
        (W, "Call suppliers", time(9, 30), time(11)),
        (W, "Vendor report", time(11), time(12, 30)),
    ]


def test_range_in_one_cell_and_am_pm():
    rows = schedule_rows(
        sheet(
            ("Time", "Activity"), ("9:30 - 11:00", "Calls"), ("2pm to 3:30pm", "Review")
        )
    )
    assert rows == [
        (W, "Calls", time(9, 30), time(11)),
        (W, "Review", time(14), time(15, 30)),
    ]


def test_no_header_and_serial_numbers_are_not_times():
    rows = schedule_rows(sheet((1, "10:00", "Standup"), (2, "10:30", "Inbox")))
    assert rows == [
        (W, "Standup", time(10), time(10, 30)),
        (W, "Inbox", time(10, 30), time(11, 30)),
    ]


def test_lines_without_a_time_become_goals():
    rows = schedule_rows(sheet(("Ship the report",), ("09:00", "10:00", "Write it")))
    assert rows[0] == (G, "Ship the report", None, None)
    assert rows[1][0] == W


def test_type_column_marks_goals():
    rows = schedule_rows(
        sheet(
            ("Type", "Task", "Time"),
            ("Goal", "Close the books", None),
            ("Work", "Ledger", "9:00-10:00"),
        )
    )
    assert [r[0] for r in rows] == [G, W]


def test_empty_and_garbage_files_are_refused():
    with pytest.raises(PlanError, match="nothing to import"):
        schedule_rows(sheet(("Start", "End", "Task")))
    with pytest.raises(PlanError, match="Couldn't read"):
        schedule_rows(SimpleUploadedFile("x.xlsx", b"not a workbook"))


@pytest.mark.django_db
def test_import_fills_the_form_without_saving(client, alice):
    client.force_login(alice)
    response = client.post(
        reverse("plans:today"),
        {
            "sheet": sheet(
                ("Start", "End", "Task"),
                ("09:00", "10:00", "Calls"),
                (None, None, "Goal for today"),
            )
        },
    )
    assert response.status_code == 200
    assert {r["text"] for r in response.context["rows"]} == {"Calls", "Goal for today"}
    assert response.context["imported"]
    assert not DailyPlan.objects.exists()
