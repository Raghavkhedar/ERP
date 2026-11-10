from django import template

from core.access import first_tab_url, has_module, held_tabs
from core.matrix import managed_companies

register = template.Library()


@register.filter
def can_open(user, module):
    """{% if user|can_open:"hr" %} shows a navbar link only to people in the module."""
    return has_module(user, module)


@register.simple_tag(takes_context=True, name="held_tabs")
def held_tabs_tag(context):
    return held_tabs(context["user"])


@register.simple_tag(takes_context=True)
def empanelment_url(context):
    """Where the sidebar's Empanelment link goes: the first tab they hold."""
    return first_tab_url(context["user"])


@register.simple_tag(takes_context=True)
def can_matrix(context):
    """Whether to show the Access matrix link: superadmins and named managers."""
    return managed_companies(context["user"]).exists()
