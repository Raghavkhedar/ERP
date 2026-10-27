from django import template

from feedback.services import is_reader
from redflags.services import has_access

register = template.Library()
register.filter("reads_feedback", is_reader)
register.filter("sees_red_flags", has_access)
