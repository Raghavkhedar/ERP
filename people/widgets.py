from django import forms
from django.utils.safestring import mark_safe

# shortcut: a short list of the countries we recruit in; add more when needed.
CODES = [
    ("+91", "India +91"),
    ("+1", "US / Canada +1"),
    ("+44", "UK +44"),
    ("+971", "UAE +971"),
    ("+966", "Saudi Arabia +966"),
    ("+974", "Qatar +974"),
    ("+968", "Oman +968"),
    ("+965", "Kuwait +965"),
    ("+973", "Bahrain +973"),
    ("+65", "Singapore +65"),
    ("+61", "Australia +61"),
    ("+977", "Nepal +977"),
    ("+880", "Bangladesh +880"),
    ("+94", "Sri Lanka +94"),
    ("+92", "Pakistan +92"),
    ("", "Other (type in full)"),
]
DEFAULT = "+91"


def split_phone(value):
    """("+91", "98765 43210") from a stored phone. A number with no code is taken
    as Indian; one with a code we don't list goes whole into the number box."""
    value = (value or "").strip()
    if not value.startswith("+"):
        return DEFAULT, value
    for code, _ in sorted(CODES, key=lambda c: -len(c[0])):
        if code and value.startswith(code):
            return code, value[len(code) :].strip()
    return "", value


class PhoneWidget(forms.Widget):
    """A country-code dropdown beside the number, saved as one string
    ("+91 98765 43210"). A plain `name` value in a post is still accepted."""

    def value_from_datadict(self, data, files, name):
        number = data.get(f"{name}_number")
        if number is None:
            return data.get(name)
        number = number.strip()
        code = data.get(f"{name}_code", DEFAULT)
        return f"{code} {number}".strip() if number else ""

    def id_for_label(self, id_):
        return f"{id_}_number" if id_ else id_

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        id_ = attrs.get("id", f"id_{name}")
        code, number = split_phone(value)
        select = forms.Select(choices=CODES).render(
            f"{name}_code",
            code,
            {
                "id": f"{id_}_code",
                "aria-label": "Country code",
                "style": "flex:none;width:8rem",
            },
            renderer,
        )
        text = forms.TextInput().render(
            f"{name}_number",
            number,
            {
                **attrs,
                "id": f"{id_}_number",
                "type": "tel",
                "inputmode": "tel",
                "style": "flex:1;min-width:0",
            },
            renderer,
        )
        return mark_safe(f'<div style="display:flex;gap:.5rem">{select}{text}</div>')
