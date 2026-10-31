from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from people.models import phone_key

from .models import CallLog, FollowUp, HRAssessment, Interview, Requisition


class RequisitionForm(forms.ModelForm):
    # The version the form was opened at; see services.save_requisition.
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Requisition
        fields = ["department", "profile", "headcount", "site", "needed_by"]
        widgets = {
            "needed_by": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }


class SourceForm(forms.Form):
    requisition = forms.ModelChoiceField(Requisition.objects.none())
    name = forms.CharField(max_length=200)
    phone = forms.CharField(max_length=30)
    email = forms.EmailField(required=False)
    source = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"list": "sources"}),
    )

    def __init__(self, *args, requisitions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requisition"].queryset = requisitions

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if len(phone_key(phone)) < 10:
            raise forms.ValidationError("Enter a phone number with at least 10 digits.")
        return phone


class ImportForm(forms.Form):
    requisition = forms.ModelChoiceField(Requisition.objects.none())
    source = forms.CharField(
        max_length=120,
        required=False,
        help_text="Used for rows with no Source column.",
        widget=forms.TextInput(attrs={"list": "sources"}),
    )
    sheet = forms.FileField(label="Excel file (.xlsx)")

    def __init__(self, *args, requisitions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requisition"].queryset = requisitions


def _when(label, **kw):
    return forms.DateTimeField(
        label=label,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
        **kw,
    )


def tomorrow_morning():
    day = timezone.localtime() + timedelta(days=1)
    return day.replace(hour=10, minute=0, second=0, microsecond=0)


class CallForm(forms.Form):
    outcome = forms.ChoiceField(
        choices=CallLog.Outcome.choices, widget=forms.RadioSelect
    )
    next_due = _when("Next follow-up", required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-filled so the usual "try again tomorrow" is one tap.
        self.fields["next_due"].initial = tomorrow_morning()


class RescheduleForm(forms.Form):
    due = _when("New date and time")
    reason = forms.ChoiceField(choices=FollowUp.Reason.choices)


class ReassignForm(forms.Form):
    owner = forms.ModelChoiceField(get_user_model().objects.none(), label="Give to")

    def __init__(self, *args, companies, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = (
            get_user_model()
            .objects.filter(is_active=True, memberships__company__in=companies)
            .distinct()
        )


class InterviewForm(forms.Form):
    result = forms.ChoiceField(
        choices=Interview.Result.choices, widget=forms.RadioSelect
    )
    next_due = _when("Call again on", required=False)
    questions = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class AssessmentForm(forms.ModelForm):
    class Meta:
        model = HRAssessment
        fields = ["decision", "level", "hold_tenure", "comments"]
        widgets = {"comments": forms.Textarea(attrs={"rows": 3})}
