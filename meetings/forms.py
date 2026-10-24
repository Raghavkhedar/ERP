from datetime import datetime

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone


class BookingForm(forms.Form):
    topic = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Leave request"}),
        help_text="What is the meeting about?",
    )


class ConferenceForm(forms.Form):
    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Quarterly review"}),
    )
    day = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    end = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    location = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "A room, or a link to the call"}),
    )
    agenda = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    invitees = forms.ModelMultipleChoiceField(
        queryset=None, widget=forms.CheckboxSelectMultiple, label="Who to invite"
    )

    def __init__(self, *args, host, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invitees"].queryset = (
            get_user_model()
            .objects.filter(is_active=True)
            .exclude(pk=host.pk)
            .order_by("first_name", "last_name", "username")
        )
        self.fields["invitees"].label_from_instance = lambda user: user.display_name

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["end"] <= data["start"]:
            self.add_error("end", "End must be after the start.")
        return data

    def times(self):
        """Aware start and end datetimes from the cleaned day and times."""
        data = self.cleaned_data
        make = timezone.make_aware
        return (
            make(datetime.combine(data["day"], data["start"])),
            make(datetime.combine(data["day"], data["end"])),
        )


class InviteMoreForm(forms.Form):
    invitees = forms.ModelMultipleChoiceField(
        queryset=None, widget=forms.CheckboxSelectMultiple, label="Invite more people"
    )

    def __init__(self, *args, conference, **kwargs):
        super().__init__(*args, **kwargs)
        taken = [
            conference.host_id,
            *conference.invitations.values_list("user_id", flat=True),
        ]
        self.fields["invitees"].queryset = (
            get_user_model()
            .objects.filter(is_active=True)
            .exclude(pk__in=taken)
            .order_by("first_name", "last_name", "username")
        )
        self.fields["invitees"].label_from_instance = lambda user: user.display_name
