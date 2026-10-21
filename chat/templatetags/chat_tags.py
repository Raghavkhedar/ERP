import zlib

from django import template

register = template.Library()


@register.filter
def avatar_hue(name):
    """A hue (0-359) that is always the same for the same name."""
    return zlib.crc32(str(name).encode()) % 360
