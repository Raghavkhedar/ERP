import re
from datetime import datetime, time, timedelta

from openpyxl import load_workbook

from .models import PlanItem
from .services import ITEM_LIMIT, TEXT_MAX, PlanError

MAX_BYTES = 1_000_000
SCAN_ROWS = 300

TEXT_HEADS = {"task", "tasks", "activity", "activities", "work", "description"}
TEXT_HEADS |= {"details", "plan", "item", "what", "agenda", "schedule", "title"}
KIND_HEADS = {"type", "kind", "category"}
TIME_HEADS = {"time", "start", "from", "end", "to", "till", "until", "slot", "timing"}
GOAL_WORDS = {"goal", "goals", "target", "objective"}

CLOCK = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?\s*([ap]\.?m\.?)?$", re.I)
RANGE_SPLIT = re.compile(r"\s*(?:-|–|—|\bto\b)\s*", re.I)


def _clock(value):
    """A cell as a time of day, or None when it isn't one.

    Excel keeps times as fractions of a day, so 0.5 is noon. Text only counts
    when it carries a colon or am/pm; a bare "3" is a serial number, not 03:00.
    """
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, float) and 0 <= value < 1:
        minutes = round(value * 24 * 60)
        return time(minutes // 60, minutes % 60) if minutes < 24 * 60 else None
    if not isinstance(value, str):
        return None
    match = CLOCK.match(value.strip())
    if not match or not (":" in value or "." in value or match.group(3)):
        return None
    hour, minute, meridiem = (
        int(match.group(1)),
        int(match.group(2) or 0),
        match.group(3),
    )
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.lower().startswith("p") else 0)
    return time(hour, minute) if hour < 24 and minute < 60 else None


def _range(value):
    """ "9:30 - 11:00" in one cell as (start, end), or None."""
    if not isinstance(value, str):
        return None
    parts = RANGE_SPLIT.split(value.strip())
    if len(parts) != 2:
        return None
    start, end = _clock(parts[0]), _clock(parts[1])
    if start is None or end is None:
        return None
    # "9:30 - 11:00 am" -> the first part has no am/pm of its own
    if (
        end.hour >= 12
        and start.hour < 12
        and not re.search(r"[ap]\.?m", parts[0], re.I)
    ):
        if re.search(r"p\.?m", parts[1], re.I) and start.hour + 12 < end.hour:
            start = start.replace(hour=start.hour + 12)
    return start, end


def _head(cell):
    return str(cell).strip().lower().rstrip(":") if cell is not None else ""


def _layout(rows):
    """Where the header row is and which columns hold the text and the type."""
    for index, row in enumerate(rows[:10]):
        heads = [_head(c) for c in row]
        known = [h for h in heads if h in TEXT_HEADS | KIND_HEADS | TIME_HEADS]
        if len(known) >= 2:
            text = next((i for i, h in enumerate(heads) if h in TEXT_HEADS), None)
            kind = next((i for i, h in enumerate(heads) if h in KIND_HEADS), None)
            return index, text, kind
    return -1, None, None


def _line(row, text_col, kind_col):
    """One sheet row as (kind, text, start, end), or None for an empty row."""
    times, text = [], None
    for i, cell in enumerate(row):
        if cell is None or i == kind_col:
            continue
        span = _range(cell)
        if span:
            times.extend(span)
        elif _clock(cell) is not None:
            times.append(_clock(cell))
        elif (
            text is None
            and (text_col is None or i == text_col)
            and isinstance(cell, str)
            and cell.strip()
        ):
            text = cell.strip()
    if text is None:
        return None
    kind = None
    if kind_col is not None and kind_col < len(row) and row[kind_col] is not None:
        word = str(row[kind_col]).strip().lower()
        kind = PlanItem.Kind.GOAL if word in GOAL_WORDS else PlanItem.Kind.WORK
    start = times[0] if times else None
    end = times[1] if len(times) > 1 else None
    return kind, text[:TEXT_MAX], start, end


def schedule_rows(upload):
    """Read an .xlsx schedule into plan rows of (kind, text, start, end).

    Lines with a time become work; lines without one become goals (unless a
    type column says otherwise). A line with only a start time ends when the
    next timed line starts, or an hour later if it is the last.
    """
    if upload.size > MAX_BYTES:
        raise PlanError("That file is too big. Keep it under 1 MB.")
    try:
        book = load_workbook(upload, read_only=True, data_only=True)
        sheet = book.active
        rows = [list(r) for r in sheet.iter_rows(max_row=SCAN_ROWS, values_only=True)]
    except Exception:
        raise PlanError(
            "Couldn't read that file. Upload an Excel .xlsx file."
        ) from None

    header, text_col, kind_col = _layout(rows)
    lines = []
    for row in rows[header + 1 :]:
        line = _line(row, text_col, kind_col)
        if line:
            lines.append(line)
    if not lines:
        raise PlanError("Found nothing to import. Each line needs some text.")

    timed = [i for i, (_, _, start, _) in enumerate(lines) if start]
    for pos, i in enumerate(timed):
        kind, text, start, end = lines[i]
        if end is None:
            following = lines[timed[pos + 1]][2] if pos + 1 < len(timed) else None
            if following and following > start:
                end = following
            else:
                bump = (
                    datetime.combine(datetime.min, start) + timedelta(hours=1)
                ).time()
                end = bump if bump > start else time(23, 59)
        lines[i] = (kind, text, start, end)

    out = []
    for kind, text, start, end in lines:
        if kind is None:
            kind = PlanItem.Kind.WORK if start else PlanItem.Kind.GOAL
        if kind == PlanItem.Kind.WORK and not start:
            kind = PlanItem.Kind.GOAL
        if kind == PlanItem.Kind.GOAL:
            start = end = None
        out.append((kind, text, start, end))
    if len(out) > ITEM_LIMIT:
        raise PlanError(
            f"That sheet has {len(out)} lines; a day's plan holds up to {ITEM_LIMIT}."
        )
    return out
