from django import template

from core.access import has_module

register = template.Library()


@register.filter
def can_open(user, module):
    """{% if user|can_open:"hr" %} shows a navbar link only to people in the module."""
    return has_module(user, module)
