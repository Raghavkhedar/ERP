from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

SUNDAY = 6
SUNDAY_MESSAGE = "Sunday is a non-working day. Pick another date."


def is_sunday(when):
    """Whether `when` is a Sunday where we work. An aware datetime is judged in
    local time: the database hands them back in UTC, which is a different day for
    anyone after midnight in India."""
    if isinstance(when, datetime) and timezone.is_aware(when):
        when = timezone.localtime(when)
    return when.weekday() == SUNDAY


def skip_sunday(when):
    """A date or datetime that lands on a Sunday moves to Monday."""
    return when + timedelta(days=1) if is_sunday(when) else when


def no_sunday(when):
    """For dates a person picks: refuse a Sunday instead of silently moving it."""
    if is_sunday(when):
        raise ValidationError(SUNDAY_MESSAGE)
    return when
