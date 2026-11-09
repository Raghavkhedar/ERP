from datetime import datetime, timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Company
from people.models import Person, phone_key
from people.services import visible_people
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


PORTALS = [
    "Naukri",
    "LinkedIn",
    "Indeed",
    "Apna",
    "WorkIndia",
    "Foundit",
    "Shine",
    "Job Hai",
    "Internshala",
    "Freshersworld",
    "TimesJobs",
    "Glassdoor",
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
    # Typed as days from today; stored as the date (needed_by).
    days = forms.IntegerField(
        min_value=0, max_value=3650, required=False, label="By when (days)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        due = self.instance.needed_by
        if due:
            self.initial["days"] = max((due - timezone.localdate()).days, 0)

    def save(self, commit=True):
        # Only a changed number moves the date, so reopening never shifts it.
        if "days" in self.changed_data:
            days = self.cleaned_data["days"]
            self.instance.needed_by = (
                None if days is None else timezone.localdate() + timedelta(days=days)
            )
        return super().save(commit)

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
            "requirements": "Job requirements",
            "reputed_company_must": "Experience in a reputed company is a must",
            "site": "Place of job",
        }
        widgets = {
            "kind": forms.RadioSelect,
            "requirements": forms.Textarea(attrs={"rows": 3}),
            "other_details": forms.Textarea(attrs={"rows": 3}),
        }


class SourceForm(forms.Form):
    requisition = forms.ModelChoiceField(Requisition.objects.none())
    name = forms.CharField(max_length=200)
    phone = forms.CharField(max_length=30, widget=PhoneWidget)
    email = forms.EmailField(required=False)
    gender = forms.ChoiceField(
        required=False, choices=Person.Gender.choices, widget=forms.RadioSelect
    )
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    # A well-known portal, or "other" with the name typed below it.
    source = forms.ChoiceField(
        required=False,
        label="Where did this number come from?",
        choices=[("", "---------")] + [(x, x) for x in PORTALS] + [("other", "Other")],
        widget=forms.Select(attrs={"x-model": "source"}),
    )
    source_other = forms.CharField(label="Source name", max_length=120, required=False)

    def __init__(self, *args, requisitions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requisition"].queryset = requisitions

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if len(phone_key(phone)) < 10:
            raise forms.ValidationError("Enter a phone number with at least 10 digits.")
        return phone

    def clean(self):
        data = super().clean()
        if data.get("source") == "other":
            name = (data.get("source_other") or "").strip()
            if not name:
                self.add_error("source_other", "Write the source's name.")
            data["source"] = name
        return data


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
        label="Tagging", choices=CallLog.Outcome.choices, widget=forms.RadioSelect
    )
    notes = forms.CharField(
        label="Status", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    next_due = forms.DateField(
        label="Next follow-up date",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    call_type = forms.ChoiceField(
        choices=CallLog.Kind.choices,
        initial=CallLog.Kind.OUTBOUND,
        widget=forms.RadioSelect,
    )
    intention = forms.ChoiceField(
        label="Next call intention", choices=FollowUp.Purpose.choices
    )
    intention_other = forms.CharField(
        label="What is the intention?", required=False, max_length=200
    )
    rescheduled = forms.BooleanField(label="Candidate rescheduled", required=False)
    reschedule_reason = forms.CharField(
        label="Reason the candidate gave",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    department_changed = forms.BooleanField(required=False)
    discuss = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-filled so the usual "try again tomorrow" is one tap.
        self.fields["next_due"].initial = tomorrow_morning().date()
        self.fields["next_due"].widget.attrs["min"] = timezone.localdate().isoformat()

    def clean_next_due(self):
        day = self.cleaned_data["next_due"]
        if day < timezone.localdate():
            raise forms.ValidationError("The next follow-up can't be before today.")
        # Only the day is asked for; the call alarm rings at the usual 10:00.
        return timezone.make_aware(datetime.combine(day, tomorrow_morning().time()))

    def clean(self):
        data = super().clean()
        for flag, text, message in (
            (
                "rescheduled",
                "reschedule_reason",
                "Write the reason the candidate gave.",
            ),
            ("intention", "intention_other", "Say what the intention is."),
        ):
            on = (
                data.get(flag) == FollowUp.Purpose.OTHER
                if flag == "intention"
                else data.get(flag)
            )
            if on and not data.get(text, "").strip():
                self.add_error(text, message)
        return data


class IncomingCallForm(CallForm):
    """A call that came in: the same questions, for a candidate picked by hand."""

    person = forms.ModelChoiceField(
        Person.objects.none(),
        widget=forms.HiddenInput,
        error_messages={"required": "Pick the candidate."},
    )

    def __init__(self, *args, companies, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].queryset = visible_people(companies)
        self.fields["call_type"].initial = CallLog.Kind.INBOUND


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
    # A well-known portal, or "other" with the name typed below it.
    portal = forms.ChoiceField(
        label="Job portal",
        choices=[("", "---------")] + [(x, x) for x in PORTALS] + [("other", "Other")],
        widget=forms.Select(attrs={"x-model": "portal"}),
    )
    portal_other = forms.CharField(label="Portal name", max_length=120, required=False)
    field_order = ["portal", "portal_other"]

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
            "keyword": "Source keyword",
            "posted_on": "Date posted",
            "post_status": "Status",
            "payment": "Payment type",
            "portal_user": "Portal user ID",
            "body": "Note (optional)",
        }
        widgets = {
            "posted_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "body": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("portal", "keyword", "posted_on", "post_status", "payment"):
            self.fields[name].required = True
        # Only our own companies (Senken, Avris), stored by name.
        names = list(Company.objects.order_by("name").values_list("name", "name"))
        old = self.instance.posting_company
        if old and (old, old) not in names:
            names.append((old, old))  # saved before the list was fixed
        self.fields["posting_company"] = forms.ChoiceField(
            label="Company", required=False, choices=[("", "---------"), *names]
        )
        # A portal outside the list is edited as "other" with its name filled in.
        portal = self.instance.portal
        if portal and portal not in PORTALS:
            self.initial["portal"], self.initial["portal_other"] = "other", portal

    def clean(self):
        data = super().clean()
        if data.get("portal") == "other":
            name = (data.get("portal_other") or "").strip()
            if not name:
                self.add_error("portal_other", "Write the portal's name.")
            data["portal"] = name
        return data
