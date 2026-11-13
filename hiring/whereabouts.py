"""The two whereabout forms filled during a call.

The mini one is a short fixed form. The major one has questions every department
answers (COMMON) plus the questions of the chosen department group (GROUPS).
Answers are stored as plain dicts on the CallLog, so a question can change
without a migration."""

from django import forms
from django.utils.dateparse import parse_date

YESNO = ["Yes", "No"]


def parse_day(value):
    """A date from text, or None when it is blank or not a real date. Django's
    parse_date raises on a date that looks right but doesn't exist (2031-02-30)."""
    try:
        return parse_date(value or "")
    except ValueError:
        return None


class DayField(forms.CharField):
    """A date kept as ISO text, so it can sit in the JSON answers."""

    def validate(self, value):
        super().validate(value)
        if value and not parse_day(value):
            raise forms.ValidationError("Enter a real date.")


# key: (kind, label). kinds: text area int date yesno rate choice:A|B multi:A|B
SPEC = {
    # mini whereabout
    "current_company": ("text", "Current company"),
    "total_experience_months": ("int", "Total experience (months)"),
    "joining_period_days": ("int", "Joining period (days)"),
    "current_address": ("area", "Current address"),
    "current_salary": ("int", "Current salary (monthly)"),
    "availability_status": ("yesno", "Availability status"),
    "notes": ("area", "Notes"),
    # common to every major whereabout
    "company_name": ("text", "Company name"),
    "time_period_months": ("int", "Time period (months)"),
    "designation": ("text", "Designation"),
    "rfl": ("text", "RFL (reason for leaving)"),
    "belongs_to": ("text", "Belongs to"),
    "last_ctc": ("int", "Last CTC (monthly)"),
    "in_hand_salary": ("int", "In-hand salary (monthly)"),
    "current_working_status": ("text", "Current working status"),
    "salary_expectation": ("int", "Salary expectation (monthly)"),
    # department questions
    "affiliation": (
        "choice:Previous|Present",
        "Affiliation (previous / present employee)",
    ),
    "family_details": ("area", "Family details with their professions"),
    "lives_with": ("text", "Lives with (kiske sath rehte hain)"),
    "trade": ("choice:Electrical|Mechanical", "Elec / Mech"),
    "multiple_sites": ("yesno", "Multiple sites"),
    "conveyance": ("int", "Conveyance (monthly)"),
    "leave": ("text", "Leave"),
    "other_payments": ("text", "Other payments"),
    "g4_electrical": ("text", "G+4 electrical completion time"),
    "g4_installation": ("text", "G+4 installation completion time"),
    "graduation": ("yesno", "Graduation"),
    "arc_welding": ("yesno", "ARC welding"),
    "pipe_welding": ("yesno", "Pipe welding"),
    "multimeter": ("yesno", "Knows how to use a multimeter"),
    "wiring_tracing": ("yesno", "Wiring tracing"),
    "iti_fitter": ("yesno", "ITI - fitter"),
    "sales_types": ("multi:Corporate|Retail|Tele", "Sales types"),
    "sales_other": ("text", "Any other type of sales"),
    "bike": ("yesno", "Bike"),
    "public_speaking": ("text", "Public speaking (topics)"),
    "english_writing": ("rate", "English: writing (1-5)"),
    "english_speaking": ("rate", "English: speaking (1-5)"),
    "english_reading": ("rate", "English: reading (1-5)"),
    "school_12th": ("text", "12th schooling name"),
    "training": ("text", "Training"),
    "profile": ("text", "Profile"),
    "permanent_address": ("area", "Permanent address"),
    "college": ("text", "University / college name"),
    "study_department": ("text", "Department"),
    "graduation_course": ("text", "Graduation course (specialization, if any)"),
    "post_graduation_course": (
        "text",
        "Post-graduation course (specialization, if any)",
    ),
    "diploma": ("text", "Diploma (specialization, if any)"),
    "other_course": ("text", "Any other certified course"),
    "currently_pursuing": ("text", "Currently pursuing"),
    "study_year": ("choice:Completion|Final|Pre-final", "Year"),
    "internship_placement": ("choice:Internship|Placement", "Internship / placement"),
    "duration": ("text", "Duration"),
    "joining_date": ("date", "Joining date"),
    "field_of_interest": ("text", "Field of interest"),
    "websites_applied": ("text", "Websites applied"),
    "ms_office": ("yesno", "Knows basic MS Word and Excel"),
    "course_branch": ("text", "Course (branch, if any)"),
    "year_completed": ("text", "Year (completed in)"),
    "excel_level": ("choice:Basic|Advanced", "MS Excel knowledge"),
}

MINI = [
    "current_company",
    "total_experience_months",
    "joining_period_days",
    "current_address",
    "current_salary",
    "availability_status",
    "notes",
]

# "department" is added by the form: it is the choice of GROUPS below.
COMMON = [
    "company_name",
    "time_period_months",
    "designation",
    "rfl",
    "current_address",
    "belongs_to",
    "last_ctc",
    "in_hand_salary",
    "current_working_status",
    "joining_period_days",
    "salary_expectation",
]

_SITES = ["multiple_sites", "conveyance", "leave", "other_payments"]
_SALES = ["sales_types", "sales_other", "other_payments"]
_STUDY = ["college", "graduation_course", "other_course", "currently_pursuing"]

GROUPS = {
    "elec_mech": (
        "Elec + Mech",
        [
            "affiliation",
            "family_details",
            "lives_with",
            "trade",
            *_SITES,
            "g4_electrical",
            "g4_installation",
        ],
    ),
    "bo": ("BO", ["graduation"]),
    "helper_welder": ("Helper cum Welder", [*_SITES, "arc_welding", "pipe_welding"]),
    "hhe": ("HHE", ["multimeter", "wiring_tracing", "iti_fitter", "multiple_sites"]),
    "sales_head": ("Sales Head", _SALES),
    "sales_lead": ("Sales Lead / Senior Sales Lead", [*_SALES, "bike"]),
    "helper": ("Helper", _SITES),
    "bo_trainer": (
        "BO cum Trainer",
        [
            "graduation",
            "public_speaking",
            "english_writing",
            "english_speaking",
            "english_reading",
            "school_12th",
            "training",
        ],
    ),
    "bo_caller": ("BO Sales Caller", ["sales_types", "sales_other"]),
    "apprentice": (
        "Apprentice and Trainee",
        [
            "profile",
            "permanent_address",
            "college",
            "study_department",
            "graduation_course",
            "post_graduation_course",
            "diploma",
            "other_course",
            "currently_pursuing",
            "study_year",
            "internship_placement",
            "duration",
            "joining_date",
            "field_of_interest",
            "websites_applied",
            "ms_office",
        ],
    ),
    "analyst": (
        "Data Analyst / Executive",
        [
            "graduation",
            "college",
            "course_branch",
            "other_course",
            "year_completed",
            "currently_pursuing",
            "excel_level",
        ],
    ),
}


def _field(key, spec=None):
    """`spec` entries may carry a third item: True when the answer is required."""
    entry = (spec or SPEC)[key]
    kind, label = entry[:2]
    kw = {"label": label, "required": len(entry) > 2 and entry[2]}
    if kind == "time":
        return forms.CharField(widget=forms.TimeInput(attrs={"type": "time"}), **kw)
    if kind == "text":
        return forms.CharField(max_length=200, **kw)
    if kind == "area":
        return forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), **kw)
    if kind == "int":
        return forms.IntegerField(min_value=0, **kw)
    if kind == "date":
        return DayField(widget=forms.DateInput(attrs={"type": "date"}), **kw)
    if kind == "yesno":
        return forms.ChoiceField(choices=[("", "-")] + [(x, x) for x in YESNO], **kw)
    if kind == "rate":
        return forms.ChoiceField(
            choices=[("", "-")] + [(str(n), str(n)) for n in range(1, 6)], **kw
        )
    how, options = kind.split(":")
    options = [(x, x) for x in options.split("|")]
    if how == "multi":
        return forms.MultipleChoiceField(
            choices=options, widget=forms.CheckboxSelectMultiple, **kw
        )
    return forms.ChoiceField(choices=[("", "-")] + options, **kw)


class WhereaboutForm(forms.Form):
    """The questions in `keys`, under `prefix` so several can share one page."""

    # The block may be hidden when it is submitted, so the browser must not insist.
    use_required_attribute = False
    spec = None  # another question list, as the interview form has

    def __init__(self, keys, *args, department=False, **kwargs):
        super().__init__(*args, **kwargs)
        fields = {k: _field(k, self.spec) for k in keys}
        if department:
            choice = forms.ChoiceField(
                label="Department",
                choices=[("", "-")] + [(k, g[0]) for k, g in GROUPS.items()],
                error_messages={"required": "Pick the department."},
            )
            fields = {"department": choice, **fields}
        self.fields = fields

    def answers(self):
        """What was filled in, without the blanks."""
        return {k: v for k, v in self.cleaned_data.items() if v not in ("", None, [])}


def summary(answers, spec=None):
    """One readable line for the timeline and the export."""
    parts = []
    for key, value in answers.items():
        label = (
            "Department"
            if key == "department"
            else (spec or SPEC).get(key, (0, key))[1]
        )
        if key == "department":
            value = GROUPS.get(value, (value,))[0]
        if isinstance(value, list):
            value = ", ".join(value)
        parts.append(f"{label}: {value}")
    return "; ".join(parts)
