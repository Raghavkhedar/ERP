from datetime import datetime
from io import BytesIO

from django.utils import timezone
from openpyxl import load_workbook

from .export import cell, workbook_response


def test_formula_text_is_quoted():
    assert cell("=SUM(A1)") == "'=SUM(A1)"
    assert cell("+1") == "'+1"
    assert cell("@x") == "'@x"
    assert cell("plain") == "plain"
    assert cell(None) == ""


def test_aware_datetime_becomes_local_naive():
    moment = timezone.make_aware(datetime(2026, 10, 28, 9, 30))
    assert cell(moment) == datetime(2026, 10, 28, 9, 30)


def test_workbook_has_headers_and_rows():
    response = workbook_response("demo", {"A": (("x", "y"), [(1, "=bad")])})
    assert "demo.xlsx" in response["Content-Disposition"]
    rows = list(load_workbook(BytesIO(response.content))["A"].values)
    assert rows == [("x", "y"), (1, "'=bad")]
