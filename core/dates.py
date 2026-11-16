from datetime import timedelta

from django.core.exceptions import ValidationError

SUNDAY = 6


def skip_sunday(when):
    """Sunday is a non-working day: a date or datetime on one moves to Monday."""
    return when + timedelta(days=1) if when.weekday() == SUNDAY else when


def no_sunday(when):
    """For dates a person picks: refuse a Sunday instead of silently moving it."""
    if when.weekday() == SUNDAY:
        raise ValidationError("Sunday is a non-working day. Pick another date.")
    return when
