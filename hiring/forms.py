from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from people.models import phone_key
from people.widgets import PhoneWidget

from .models import (
    CallLog,
    FollowUp,
    HRAssessment,
    Interview,
    Requisition,
    RequisitionPost,
)

LANGUAGES = [
    (x, x)
    for x in (
        "Hindi English Marathi Gujarati Bengali Tamil Telugu Kannada Malayalam "
        "Punjabi Odia Urdu"
    ).split()
]


class RequisitionForm(forms.ModelForm):
    languages = forms.MultipleChoiceField(
        choices=LANGUAGES,
        required=False,
        label="Language fluency",
        widget=forms.CheckboxSelectMultiple,
    )
    # The version the form was opened at; see services.save_requisition.
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Requisition
        fields = [
            "kind",
            "department",
            "sub_department",
            "profile",
            "headcount",
            "experience_years",
            "employment",
            "needed_by",
            "urgency",
            "gender",
            "requirements",
            "languages",
            "industry",
            "education",
            "previous_employment_restriction",
            "reputed_company_must",
            "exposure",
            "budget",
            "physical_restriction",
            "domicile_restriction",
            "age_restriction",
            "site",
            "other_details",
        ]
        labels = {
            "kind": "Is this a new or a backfill requisition?",
            "profile": "Designation",
            "headcount": "Number of openings",
            "experience_years": "Years of experience",
            "needed_by": "Needed by",
            "requirements": "Job requirements",
            "reputed_company_must": "Experience in a reputed company is a must",
            "site": "Place of job",
        }
        widgets = {
            "kind": forms.RadioSelect,
            "needed_by": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "requirements": forms.Textarea(attrs={"rows": 3}),
            "other_details": forms.Textarea(attrs={"rows": 3}),
        }


class SourceForm(forms.Form):
    requisition = forms.ModelChoiceField(Requisition.objects.none())
    name = forms.CharField(max_length=200)
    phone = forms.CharField(max_length=30, widget=PhoneWidget)
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


class ScheduleCallForm(forms.Form):
    due = _when("Call on")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due"].initial = tomorrow_morning()


class ShiftForm(forms.Form):
    group = forms.ChoiceField(choices=[(g, g) for g in ("overdue", "today", "later")])
    day = forms.DateField(
        label="Move to",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
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


class StartOfferForm(forms.Form):
    amount = forms.DecimalField(
        label="Monthly offer", max_digits=10, decimal_places=2, min_value=1
    )
    note = forms.CharField(required=False, max_length=300)


class RoundForm(forms.Form):
    amount = forms.DecimalField(
        label="We offer", max_digits=10, decimal_places=2, min_value=1
    )
    counter = forms.DecimalField(
        label="They ask for",
        max_digits=10,
        decimal_places=2,
        min_value=1,
        required=False,
    )
    note = forms.CharField(required=False, max_length=300)


class AcceptForm(forms.Form):
    joining_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )


class DeclineForm(forms.Form):
    reason = forms.CharField(required=False, max_length=200)


class JoinedForm(forms.Form):
    joined_on = forms.DateField(
        label="Joined on",
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )


class CommentForm(forms.ModelForm):
    body = forms.CharField(
        label="Message", widget=forms.Textarea(attrs={"rows": 3}), max_length=4000
    )

    class Meta:
        model = RequisitionPost
        fields = ["body"]


class JobPostForm(forms.ModelForm):
    class Meta:
        model = RequisitionPost
        fields = [
            "portal",
            "keyword",
            "posted_on",
            "post_status",
            "payment",
            "portal_user",
            "posting_company",
            "body",
        ]
        labels = {
            "portal": "Job portal",
            "keyword": "Source keyword",
            "posted_on": "Date posted",
            "post_status": "Status",
            "payment": "Payment type",
            "portal_user": "Portal user ID",
            "posting_company": "Company",
            "body": "Note (optional)",
        }
        widgets = {
            "posted_on": forms.DateInput(attrs={"type": "date"}),
            "body": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("portal", "keyword", "posted_on", "post_status", "payment"):
            self.fields[name].required = True
