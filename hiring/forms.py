import json
from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.utils import timezone

from core.dates import SUNDAY_MESSAGE, is_sunday, no_sunday, skip_sunday
from core.models import AccessGrant, Company
from people.models import Person, phone_key
from people.services import visible_people
from people.widgets import PhoneWidget

from . import whereabouts
from .models import (
    CallLog,
    FollowUp,
    Requisition,
    RequisitionPost,
    day_start,
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

    def __init__(self, *args, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        due = self.instance.needed_by
        if due:
            self.initial["days"] = max((due - timezone.localdate()).days, 0)
        # Which company it belongs to: asked when releasing in the all-companies
        # view, and on edit so a wrong one can be fixed, but only until sourcing
        # starts (sourced numbers and people cards are filed under the company).
        if companies and len(companies) > 1:
            editing = bool(self.instance.pk)
            field = forms.ModelChoiceField(
                Company.objects.filter(pk__in=[c.pk for c in companies]),
                empty_label=None if editing else "Choose a company",
                required=not editing,
                initial=self.instance.company if editing else None,
            )
            field.disabled = editing and self.instance.sourced.exists()
            self.fields["company"] = field

    def clean_company(self):
        company = self.cleaned_data["company"]
        if not company:  # left out on edit: stays where it is
            return self.instance.company
        # shortcut: checked at save time without a row lock, so sourcing started
        # in the same instant could slip through; lock if that ever matters.
        if (
            self.instance.pk
            and company != self.instance.company
            and self.instance.sourced.exists()
        ):
            raise forms.ValidationError("Sourcing has started, so it can't move.")
        return company

    def save(self, commit=True):
        if "company" in self.fields:
            self.instance.company = self.cleaned_data["company"]
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
    payment = forms.ChoiceField(
        required=False,
        label="Free or paid",
        choices=[("", "---------"), ("Free", "Free"), ("Paid", "Paid")],
    )

    experience_months = forms.IntegerField(
        required=False, min_value=0, max_value=1200, label="Experience (months)"
    )
    expected_salary = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        label="Expected salary (monthly)",
    )

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


class DayField(forms.DateField):
    """A date, kept as the start of that day: follow-ups have no time."""

    widget = forms.DateInput(
        attrs={"type": "date", "data-no-sunday": ""}, format="%Y-%m-%d"
    )

    def clean(self, value):
        day = super().clean(value)
        return day_start(no_sunday(day)) if day else day


def _when(label, **kw):
    return DayField(label=label, **kw)


class CallForm(forms.Form):
    outcome = forms.ChoiceField(
        label="Tagging", choices=CallLog.Outcome.choices, widget=forms.RadioSelect
    )
    notes = forms.CharField(
        label="Status", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    next_due = forms.DateField(
        label="Next follow-up date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    call_type = forms.ChoiceField(
        choices=CallLog.Kind.choices,
        initial=CallLog.Kind.OUTBOUND,
        widget=forms.RadioSelect,
    )
    intention = forms.ChoiceField(
        label="Next call intention", choices=FollowUp.Purpose.choices, required=False
    )
    # Candidate on hold / CTLF: no date yet, so no next follow-up is opened.
    tbd = forms.BooleanField(label="Date to be decided", required=False)
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
    mini_on = forms.BooleanField(required=False)
    major_on = forms.BooleanField(required=False)

    def __init__(self, *args, mini_initial=None, major_initial=None, **kwargs):
        super().__init__(*args, **kwargs)
        data = self.data if self.is_bound else None
        self.mini = whereabouts.WhereaboutForm(
            whereabouts.MINI, data, prefix="mini", initial=mini_initial
        )
        self.major = whereabouts.WhereaboutForm(
            whereabouts.COMMON,
            data,
            prefix="major",
            department=True,
            initial=major_initial,
        )
        self.earlier = (
            whereabouts.read_jobs(self.data)[0]
            if self.is_bound
            else (major_initial or {}).get("earlier_jobs", [])
        )
        self.groups = {
            key: whereabouts.WhereaboutForm(
                keys, data, prefix=key, initial=major_initial
            )
            for key, (_, keys) in whereabouts.GROUPS.items()
        }
        for key, (label, _) in whereabouts.GROUPS.items():
            self.groups[key].title = label
        # Pre-filled so the usual "try again tomorrow" is one tap.
        self.fields["next_due"].initial = skip_sunday(
            timezone.localdate() + timedelta(days=1)
        )
        self.fields["next_due"].widget.attrs["min"] = timezone.localdate().isoformat()
        self.fields["next_due"].widget.attrs["data-no-sunday"] = ""

    @property
    def earlier_json(self):
        return json.dumps(self.earlier)

    def clean_next_due(self):
        day = self.cleaned_data["next_due"]
        if not day or self.data.get("tbd"):
            return None
        if day < timezone.localdate():
            raise forms.ValidationError("The next follow-up can't be before today.")
        return day_start(no_sunday(day))

    def clean(self):
        data = super().clean()
        if data.get("tbd"):
            data["next_due"], data["intention"] = None, FollowUp.Purpose.CALL
        else:
            for name in ("next_due", "intention"):
                if (
                    name in self.fields
                    and not data.get(name)
                    and name not in self.errors
                ):
                    self.add_error(name, "This field is required.")
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
        data["mini_whereabout"] = data["major_whereabout"] = {}
        if data.get("mini_on"):
            if self.mini.is_valid():
                data["mini_whereabout"] = self.mini.answers()
            else:
                self.add_error(None, "Check the mini whereabout.")
        if data.get("major_on"):
            group = self.groups.get(self.major.data.get("major-department"))
            jobs, error = whereabouts.read_jobs(self.data)
            if error:
                self.add_error(None, error)
            if self.major.is_valid() and group and group.is_valid() and not error:
                data["major_whereabout"] = {
                    **self.major.answers(),
                    **group.answers(),
                    **({"earlier_jobs": jobs} if jobs else {}),
                }
            elif not error:
                self.add_error(None, "Check the major whereabout.")
        return data


class CallLogEditForm(CallForm):
    """Fix a call after it was logged: the same questions. The next call date and
    intention show while the follow-up this call opened is still pending, or when it
    opened none (TBD), where a date now opens one. Once it closed they are hidden."""

    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, log, followup=None, open_next=False, **kwargs):
        kwargs.setdefault(
            "initial",
            dict(
                outcome=log.outcome,
                notes=log.notes,
                call_type=log.call_type,
                rescheduled=log.rescheduled,
                reschedule_reason=log.reschedule_reason,
                department_changed=log.department_changed,
                discuss=log.discussed,
                mini_on=bool(log.mini_whereabout),
                major_on=bool(log.major_whereabout),
                version=log.version,
            ),
        )
        super().__init__(
            *args,
            mini_initial=log.mini_whereabout,
            major_initial=log.major_whereabout,
            **kwargs,
        )
        if followup:
            self.fields["next_due"].initial = timezone.localtime(followup.due).date()
            self.fields["intention"].initial = followup.purpose
            self.fields["intention_other"].initial = followup.purpose_other
        elif open_next:
            self.fields["tbd"].initial = True
        else:
            for name in ("next_due", "intention", "intention_other", "tbd"):
                del self.fields[name]


class IncomingCallForm(CallForm):
    """A call that came in: the same questions, for a candidate picked by hand."""

    person = forms.ModelChoiceField(
        Person.objects.none(),
        widget=forms.HiddenInput,
        error_messages={"required": "Pick the candidate."},
    )

    def __init__(self, *args, companies, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].queryset = visible_people(companies, archived=True)
        self.fields["call_type"].initial = CallLog.Kind.INBOUND


class RescheduleForm(forms.Form):
    due = _when("New date")
    reason = forms.ChoiceField(choices=FollowUp.Reason.choices)

    def clean_due(self):
        if self.cleaned_data["due"].date() < timezone.localdate():
            raise forms.ValidationError("Pick a day that is not before today.")
        return self.cleaned_data["due"]


class ScheduleCallForm(forms.Form):
    due = _when("Call on")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due"].initial = skip_sunday(
            timezone.localdate() + timedelta(days=1)
        )


class ReassignForm(forms.Form):
    owner = forms.ModelChoiceField(get_user_model().objects.none(), label="Give to")

    def __init__(self, *args, companies, **kwargs):
        super().__init__(*args, **kwargs)
        # Only people who can open the queues: a follow-up given to anyone else
        # would sit where they can't see it.
        can_open = AccessGrant.objects.filter(
            module="recruitment",
            section__in=("screening", "calling", "selecting", "hiring", "onboarding"),
            company__in=companies,
            company__memberships__user=F("user"),
        ).values("user")
        self.fields["owner"].queryset = (
            get_user_model()
            .objects.filter(is_active=True, memberships__company__in=companies)
            .filter(Q(is_superuser=True) | Q(pk__in=can_open))
            .distinct()
        )


class BulkForm(ReassignForm):
    """Assign or move many follow-ups: the ticked ones, or all a filter matches."""

    scope = forms.ChoiceField(choices=[("ticked", "Ticked"), ("all", "All matching")])
    do = forms.ChoiceField(choices=[("assign", "Assign"), ("move", "Move")])
    day = forms.DateField(required=False)
    reason = forms.ChoiceField(choices=FollowUp.Reason.choices, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].required = False

    def clean(self):
        data = super().clean()
        if data.get("do") == "assign" and not data.get("owner"):
            self.add_error("owner", "Pick who to give them to.")
        if data.get("do") == "move":
            if not data.get("day") or data["day"] < timezone.localdate():
                self.add_error("day", "Pick a day that is not before today.")
            elif is_sunday(data["day"]):
                self.add_error("day", SUNDAY_MESSAGE)
            if not data.get("reason"):
                self.add_error("reason", "Pick a reason for the move.")
        return data


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

    def __init__(self, *args, floor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.floor = floor  # the day they accepted the offer

    def clean_joined_on(self):
        day = self.cleaned_data["joined_on"]
        if day > timezone.localdate():
            raise forms.ValidationError("They can't have joined in the future.")
        if self.floor and day < self.floor:
            raise forms.ValidationError(
                f"They accepted on {self.floor:%d/%m/%Y}; join on or after it."
            )
        return day

    resources = forms.CharField(
        label="Resources allotted",
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    sim_allotted = forms.ChoiceField(
        label="SIM allotted",
        choices=[("Yes", "Yes"), ("No", "No")],
        widget=forms.RadioSelect,
    )
    notes = forms.CharField(
        required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 2})
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
            "portal_user",
            "posting_company",
            "body",
        ]
        labels = {
            "keyword": "Source keyword",
            "posted_on": "Date posted",
            "post_status": "Status",
            "portal_user": "Portal user ID",
            "body": "Note (optional)",
        }
        widgets = {
            "posted_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "body": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("portal", "keyword", "posted_on", "post_status"):
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
