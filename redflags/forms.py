from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from tasks.forms import FilesMixin

from .models import Status


class PersonField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f"{user.display_name} ({user.username})"


class RedFlagForm(FilesMixin, forms.Form):
    raised_against = PersonField(
        queryset=get_user_model().objects.none(),
        label="Raised against",
        empty_label="Choose a person",
        error_messages={"required": "Choose who this is about."},
    )
    incident_date = forms.DateField(
        label="Incident date",
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={"required": "Enter the date it happened."},
    )
    incident = forms.CharField(
        label="Incident",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "What happened?"}),
        error_messages={"required": "Describe the incident."},
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["raised_against"].queryset = (
            get_user_model()
            .objects.filter(is_active=True)
            .exclude(pk=user.pk)
            .order_by("first_name", "username")
        )
        self.fields["incident_date"].widget.attrs["max"] = (
            timezone.localdate().isoformat()
        )

    def clean_incident_date(self):
        date = self.cleaned_data["incident_date"]
        if date > timezone.localdate():
            raise forms.ValidationError("The incident can't be in the future.")
        return date

    def clean_incident(self):
        incident = self.cleaned_data["incident"].strip()
        if not incident:
            raise forms.ValidationError("Describe the incident.")
        return incident


class NoteForm(forms.Form):
    body = forms.CharField(
        label="Private note",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Write a note."},
    )

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Write a note.")
        return body


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=Status.choices)
