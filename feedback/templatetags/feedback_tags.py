from django import template

from feedback.services import is_reader

register = template.Library()
register.filter("reads_feedback", is_reader)
