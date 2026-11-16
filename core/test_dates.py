from datetime import date, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError

from core.dates import no_sunday, skip_sunday

SUNDAY, MONDAY = date(2026, 11, 15), date(2026, 11, 16)


def test_skip_sunday_moves_only_sundays():
    assert skip_sunday(SUNDAY) == MONDAY
    assert skip_sunday(MONDAY) == MONDAY
    assert skip_sunday(datetime(2026, 11, 15, 9)) == datetime(2026, 11, 16, 9)
    assert skip_sunday(SUNDAY - timedelta(days=1)) == date(2026, 11, 14)


def test_no_sunday_rejects_sunday():
    assert no_sunday(MONDAY) == MONDAY
    with pytest.raises(ValidationError):
        no_sunday(SUNDAY)


def test_an_aware_datetime_is_judged_in_local_time():
    from zoneinfo import ZoneInfo

    utc = ZoneInfo("UTC")
    # Sunday 19:00 UTC is Monday 00:30 in India: a working day.
    monday_early = datetime(2026, 11, 15, 19, 0, tzinfo=utc)
    assert skip_sunday(monday_early) == monday_early
    assert no_sunday(monday_early) == monday_early
    # Sunday 01:30 UTC is Sunday 07:00 in India.
    sunday_morning = datetime(2026, 11, 15, 1, 30, tzinfo=utc)
    assert skip_sunday(sunday_morning) == sunday_morning + timedelta(days=1)
    with pytest.raises(ValidationError):
        no_sunday(sunday_morning)
