from django import forms
from django.utils import timezone

from .services import SLOT_LENGTHS


class OpenSlotsForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    end = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    minutes = forms.TypedChoiceField(
        label="Slot length",
        choices=[(m, f"{m} minutes") for m in SLOT_LENGTHS],
        coerce=int,
        initial=30,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].widget.attrs["min"] = timezone.localdate().isoformat()


class BookingForm(forms.Form):
    topic = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Leave request"}),
        help_text="What is the meeting about?",
    )
