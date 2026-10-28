"""Excel downloads: one workbook per export, one sheet per related table."""

from datetime import date, datetime
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_WIDTH = 60
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def cell(value):
    """A value Excel can store, with user text made safe to open.

    Text starting with = + - @ would run as a formula in Excel, so it gets a
    leading apostrophe-style quote. Aware datetimes become local wall time.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value).replace(tzinfo=None)
        return value.replace(microsecond=0)
    if isinstance(value, (date, bool, int, float)):
        return value
    text = str(value)
    if text.startswith(FORMULA_STARTS):
        return "'" + text
    return text


def workbook_response(filename, sheets):
    """Download for `sheets`, a {name: (headers, rows)} mapping."""
    book = Workbook()
    book.remove(book.active)
    for name, (headers, rows) in sheets.items():
        sheet = book.create_sheet(name[:31])
        sheet.append(list(headers))
        for row in rows:
            sheet.append([cell(value) for value in row])
        for head in sheet[1]:
            head.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            widest = max(len(str(c.value)) for c in column if c.value is not None)
            sheet.column_dimensions[column[0].column_letter].width = min(
                widest + 2, MAX_WIDTH
            )
    if not book.sheetnames:
        book.create_sheet("Empty")
    out = BytesIO()
    book.save(out)
    response = HttpResponse(out.getvalue(), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def stamp(name):
    """'tasks-2026-10-28': a dated file name."""
    return f"{name}-{timezone.localdate():%Y-%m-%d}"
