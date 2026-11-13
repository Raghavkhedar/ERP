from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from openpyxl import load_workbook

from people.models import phone_key

from .services import lock_numbers, source_number

MAX_BYTES = 1_000_000
MAX_ROWS = 2000

HEADS = {
    "name": {"name", "candidate", "candidate name", "full name"},
    "phone": {"phone", "mobile", "mobile no", "phone no", "contact", "number"},
    "email": {"email", "e-mail", "email id"},
    "source": {"source", "keyword", "source keyword"},
}


# The longest each cell may be: the columns it lands in.
LIMITS = {"name": 200, "phone": 30, "email": 254, "source": 120}


class SheetError(Exception):
    pass


def _too_long(cell, row):
    for key, limit in LIMITS.items():
        if len(cell(row, key)) > limit:
            return f"{key} is longer than {limit} characters"
    if email := cell(row, "email"):
        try:
            validate_email(email)
        except ValidationError:
            return "not a valid email"
    return ""


def _text(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # Excel stores 9876543210 as 9876543210.0
    return "" if value is None else str(value).strip()


def import_numbers(requisition, upload, user, source=""):
    """Source every row of an .xlsx with name and phone columns (email and source
    optional). Returns (new, duplicates, skipped) where skipped is a list of
    (row number, reason). Rows are all-or-nothing only for unreadable files."""
    if upload.size > MAX_BYTES:
        raise SheetError("That file is too big. Keep it under 1 MB.")
    try:
        sheet = load_workbook(upload, read_only=True, data_only=True).active
        rows = [
            list(r) for r in sheet.iter_rows(max_row=MAX_ROWS + 2, values_only=True)
        ]
    except Exception:
        raise SheetError(
            "Couldn't read that file. Upload an Excel .xlsx file."
        ) from None
    while rows and not any(c not in (None, "") for c in rows[-1]):
        rows.pop()  # Excel keeps formatted empty rows below the data
    if len(rows) > MAX_ROWS + 1:
        raise SheetError(f"That sheet has more than {MAX_ROWS} rows. Split it up.")

    heads = [_text(c).lower() for c in rows[0]] if rows else []
    cols = {
        k: next((i for i, h in enumerate(heads) if h in v), None)
        for k, v in HEADS.items()
    }
    if cols["name"] is None or cols["phone"] is None:
        raise SheetError("The first row needs Name and Phone headings.")

    def cell(row, key):
        i = cols[key]
        return _text(row[i]) if i is not None and i < len(row) else ""

    new = duplicates = 0
    skipped = []
    with transaction.atomic():
        lock_numbers(
            requisition.company_id,
            [k for r in rows[1:] if len(k := phone_key(cell(r, "phone"))) >= 10],
        )
        for n, row in enumerate(rows[1:], start=2):
            if not any(c not in (None, "") for c in row):
                continue
            if not cell(row, "name"):
                skipped.append((n, "no name"))
                continue
            if why := _too_long(cell, row):
                skipped.append((n, why))
                continue
            try:
                made = source_number(
                    requisition,
                    cell(row, "name"),
                    cell(row, "phone"),
                    user,
                    source=cell(row, "source") or source,
                    email=cell(row, "email"),
                )
            except ValueError as exc:
                skipped.append((n, str(exc)))
                continue
            duplicates += made.is_duplicate
            new += not made.is_duplicate
    return new, duplicates, skipped
