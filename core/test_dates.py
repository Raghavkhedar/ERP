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
