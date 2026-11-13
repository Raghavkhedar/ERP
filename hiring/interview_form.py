"""The interview form: questions every candidate answers (COMMON) plus the
questions of the profile that the department and sub-department point to
(PROFILE_OF), and the HR assessment (PFA).
Answers are stored as plain dicts on the Interview, so a question can change
without a migration. Education and vehicle rows are lists of dicts."""

import re

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from people.models import Person

from . import whereabouts
from .models import HRAssessment, Requisition

YESNO = ["Yes", "No"]

# key: (kind, label, required). kinds as in whereabouts.SPEC, plus time.
SPEC = {
    "date": ("date", "Date", True),
    "place_of_assessment": ("text", "Place of assessment", True),
    "place_of_assessment_other": ("text", "Place of assessment (others)"),
    "email": ("text", "Email"),
    "temporary_address": ("area", "Temporary address", True),
    "previous_temporary_stays": ("area", "Previous temporary stays"),
    "permanent_address": ("area", "Permanent address", True),
    "highest_education": ("text", "Highest education", True),
    "experience_months": ("int", "Total experience (months)", True),
    "departments_worked_in": ("text", "Departments worked in", True),
    "last_ctc": ("area", "Last CTC including conveyance etc (detailed)", True),
    "expected_salary": ("int", "Expected salary (monthly)", True),
    "family": ("area", "Family", True),
    "close_family": (
        "area",
        "Close family members: father, mother, sister, brother, wife, kids, "
        "their professions and other details",
    ),
    "away_from_family": ("area", "In case putting up away from family", True),
    "roommate": ("area", "Details of roommate or relatives"),
    "joining_days": ("int", "Joining period (days)", True),
    "place_of_birth": ("text", "Place of birth", True),
    "date_of_birth": ("date", "Date of birth", True),
    "time_of_birth": ("time", "Time of birth", True),
    "alternate_phone": ("text", "Alternate no."),
    "assessor": ("text", "Assessor"),
    "vehicle_status": ("choice:Has a vehicle|No vehicle", "Vehicle status", True),
    # The HR assessment (PFA). Interview status and level live on HRAssessment.
    "skills": ("area", "Skills after interview"),
    "offer_given": ("int", "Offer given (monthly, if any)"),
    "salary_discussion": ("area", "Expected salary discussion"),
    "unique_id": ("text", "Unique identification"),
    "questions_asked": ("area", "Questions asked"),
    "next_follow_up": ("date", "Next follow up date"),
    "hr_form_submitted": ("yesno", "HR form submitted"),
    "closed": ("yesno", "Interview closed"),
    "closed_reason": ("text", "Interview closed reason"),
}

COMMON = [
    "date", "place_of_assessment", "place_of_assessment_other", "email",
    "temporary_address", "previous_temporary_stays", "permanent_address",
    "highest_education", "experience_months", "departments_worked_in",
    "last_ctc", "expected_salary", "family", "close_family",
    "away_from_family", "roommate", "joining_days", "place_of_birth",
    "date_of_birth", "time_of_birth", "alternate_phone", "vehicle_status",
]  # fmt: skip

PFA = [
    "skills", "offer_given", "salary_discussion", "unique_id", "questions_asked",
    "next_follow_up", "hr_form_submitted", "closed", "closed_reason",
]  # fmt: skip

# How the form groups the common questions on the page (vehicle_status sits with
# the Vehicle table). Every COMMON key is in exactly one group.
SECTIONS = [
    (
        "Candidate",
        [
            "date", "assessor", "place_of_assessment", "place_of_assessment_other",
            "email", "alternate_phone",
        ],
    ),
    (
        "Where they live",
        [
            "temporary_address", "previous_temporary_stays", "permanent_address",
            "away_from_family", "roommate",
        ],
    ),
    (
        "Work and pay",
        [
            "highest_education", "experience_months", "departments_worked_in",
            "last_ctc", "expected_salary", "joining_days",
        ],
    ),
    ("Family", ["family", "close_family"]),
    ("Birth", ["place_of_birth", "date_of_birth", "time_of_birth"]),
]  # fmt: skip

# Extra questions, used by some profiles only.
SPEC.update(
    {
        "trade": ("choice:Electrical|Mechanical|Both", "Department"),
    }
)

# Elec + Mech: the Department answer decides which list of work the candidate is
# asked about. Each item is a yes/no: can they do it.
ELECTRICAL = {
    "elec_wiring_bunch": "Wiring bunch",
    "elec_motor_encoder": "3-phase connection into motor, encoder connection",
    "elec_junction_box": (
        "Junction box connection, field wiring, travelling cable connection "
        "in controller with ferrule and thimble"
    ),
    "elec_limit": "Limit fix and connections",
    "elec_landing_doors": "Landing doors connections",
    "elec_reed_switch": "Reed switch fix and connections",
    "elec_lop_cop": "LOP and COP fix and connections",
    "elec_alarm_blower": "Alarm, fireman, blower fix and connections",
    "elec_magnet_levelling": "Magnet fix and levelling",
    "elec_hoist_learning": "Hoist learning",
    "elec_car_header": "Car header or door, door sensor fix",
    "elec_door_drive": "Door drive connections",
    "elec_door_sensor": "Door sensor connections",
}
MECHANICAL = {
    "mech_reading_marking": "Reading and marking",
    "mech_drilling_bracket": "Drilling and bracket",
    "mech_rails_hoisting": "Guide rails hoisting",
    "mech_rails_alignment": "Guide rails alignment",
    "mech_door_frame": "Door frame",
    "mech_landing_door": "Landing door",
    "mech_landing_header": "Landing header",
    "mech_motor_alignment": "Motor alignment",
    "mech_car_counter_frame": "Car and counter frame alignment",
    "mech_roping": "Roping",
}
SPEC.update({k: ("yesno", v) for k, v in {**ELECTRICAL, **MECHANICAL}.items()})

# profile -> (the choosing question, [(heading, answers that show it, keys)]) for
# questions that show only after another answer. "Both" shows both lists.
CONDITIONAL = {
    "elec_mech": (
        "trade",
        [
            ("Electrical", ["Electrical", "Both"], list(ELECTRICAL)),
            ("Mechanical", ["Mechanical", "Both"], list(MECHANICAL)),
        ],
    )
}

# profile key: (label, extra question keys, extra tables). Every profile also gets
# the Vehicle and Educational background tables; most add Work experience.
_WORK = ["work"]
PROFILES = {
    "sales_head": ("Sales Head / Sales Lead", [], _WORK),
    "office_boy": ("Office Boy", [], _WORK),
    "elec_mech": ("Elec + Mech", ["trade", *ELECTRICAL, *MECHANICAL], _WORK),
    "helper": ("Helper", [], _WORK),
    "hhe": ("HHE", [], _WORK),
    "bo": ("BO", [], _WORK),
    "bo_trainer": ("BO Cum Trainer", [], _WORK),
    "helper_welder": ("Helper Cum Welder", [], _WORK),
    "bo_sales_caller": ("BO Sales Caller", [], _WORK),
    "data": ("Data Analyst / Data Executive", [], _WORK),
    "": ("Other", [], _WORK),  # any other department / sub-department
}

# (department, sub-department) -> profile. The questions follow these two.
PROFILE_OF = {
    ("sales", "Sales Head"): "sales_head",  # also Sales Lead / Senior Sales Lead
    ("bo", "Office Boy"): "office_boy",
    ("operations", "Helper"): "helper",
    ("operations", "HHE"): "hhe",
    ("operations", "Elec + Mech"): "elec_mech",
    ("bo", "Back Office Executive"): "bo",
    ("training", "Trainer"): "bo_trainer",
    ("operations", "Welder"): "helper_welder",
    ("sales", "Customer Sales Executive"): "bo_sales_caller",
    ("bo", "Data Analyst"): "data",
}


def profile_for(department, sub_department):
    return PROFILE_OF.get((department, (sub_department or "").strip()), "")


def label(interview):
    """What an interview was for: the department, or the old profile name."""
    a = interview.answers
    if a.get("department"):
        dept = Requisition.Department(a["department"]).label
        return f"{dept} / {a['sub_department']}" if a.get("sub_department") else dept
    return PROFILES.get(interview.profile, (interview.profile,))[0]


WORK = {
    "place": "Place of duty",
    "organization": "Name of organization",
    "start": "Start date",
    "current": "Currently working",
    "end": "End date",
    "duration": "Duration (months)",
    "does": "What organization does",
    "role": "What was your role in the organization",
    "salary": "Salary (monthly)",
    "rfl": "RFL",
}
# Input type of the table columns that aren't plain text.
COLUMN_TYPES = {
    "start": "date",
    "end": "date",
    "current": "yesno",
    "duration": "number",
    "salary": "number",
}

EDUCATION = {
    "qualification": "Academic qualification",
    "board": "Board/University",
    "school": "School/College name",
    "year": "Pass out year",
    "course": "Course",
    "specialization": "Specialization (if any)",
    "grade": "CGPA/Percentage/Grade",
}
VEHICLE = {
    "vehicle": "Vehicle",
    "own": "Own",
    "driving": "Driving status",
    "dl": "DL status",
}

# answers key -> (form-field prefix, title, columns)
TABLES = {
    "vehicles": ("veh", "Vehicle", VEHICLE),
    "work": ("work", "Work experience", WORK),
    "education": ("edu", "Educational background", EDUCATION),
}


def table_keys(profile):
    """The tables a profile shows: vehicle, its own, then education."""
    extra = PROFILES.get(profile, PROFILES[""])[2]
    return ["vehicles", *extra, "education"]


def work_months(start, end, current, today):
    """Whole months between two dates (to today while still working there), or
    None when a date is missing, the end is before the start, or it hasn't begun."""
    began = whereabouts.parse_day(start)
    left = today if current == "Yes" else whereabouts.parse_day(end)
    if not began or not left or left < began or began > today:
        return None
    return (
        (left.year - began.year) * 12
        + left.month
        - began.month
        - (left.day < began.day)
    )


def _clean_work(row):
    """Someone still working there has no end date, and the months are worked out
    from the dates, whatever was typed."""
    if row["current"] == "Yes":
        row["end"] = ""
    months = work_months(row["start"], row["end"], row["current"], timezone.localdate())
    row["duration"] = "" if months is None else str(months)
    return row


def read_tables(post, profile):
    got = {k: rows(post, TABLES[k][0], TABLES[k][2]) for k in table_keys(profile)}
    got["work"] = [_clean_work(r) for r in got.get("work", [])]
    if post.get("vehicle_status") != "Has a vehicle":
        got["vehicles"] = []
    return got


def table_shows():
    """Per table, an Alpine test for the profiles that show it."""
    return {
        k: "[" + ",".join(f"'{p}'" for p in PROFILES if k in table_keys(p)) + "]"
        for k in TABLES
    }


class AnswersForm(whereabouts.WhereaboutForm):
    spec = SPEC

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, field in self.fields.items():  # yes/no reads best as two buttons
            if SPEC.get(key, ("",))[0] == "yesno":
                field.widget = forms.RadioSelect()
                field.choices = [(x, x) for x in YESNO]


MAX_ROWS = 50  # per table; the page stops adding rows here, the server keeps to it


def rows(post, prefix, columns):
    """The filled rows of a repeating table: one input per column, same names."""
    lists = [post.getlist(f"{prefix}_{c}") for c in columns]
    n = max(len(x) for x in lists)
    out = [
        {
            c: (x[i] if i < len(x) else "").strip()
            for c, x in zip(columns, lists, strict=True)
        }
        for i in range(n)
    ]
    return [r for r in out if any(r.values())][:MAX_ROWS]


def offer_amount(value):
    """The monthly amount in an offer_given answer. It used to be free text, so
    a saved "15000 + incentive" gives 15000 and anything without digits gives 0."""
    if isinstance(value, int):
        return value
    found = re.search(r"\d[\d,]*", str(value or ""))
    return int(found.group().replace(",", "")) if found else 0


def summary(answers):
    return whereabouts.summary({k: v for k, v in answers.items() if k in SPEC}, SPEC)


class InterviewForm(AnswersForm):
    """The common questions, a department and sub-department, and the questions of the
    profile they point to."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(COMMON, *args, **kwargs)
        assessor = forms.ModelChoiceField(
            get_user_model().objects.filter(is_active=True),
            label="Assessor",
            initial=user,
        )
        department = forms.ChoiceField(
            label="Department",
            choices=[("", "-"), *Requisition.Department.choices],
            error_messages={"required": "Pick the department."},
        )
        sub = forms.CharField(
            label="Sub-department",
            required=False,
            max_length=120,
            widget=forms.TextInput(attrs={"list": "sub-departments"}),
        )
        self.fields = {
            "department": department,
            "sub_department": sub,
            **self.fields,
            "assessor": assessor,
        }
        data = args[0] if args else None
        self.groups = {
            k: AnswersForm(keys, data, prefix=k, initial=kwargs.get("initial"))
            for k, (_, keys, _tables) in PROFILES.items()
            if keys
        }
        for key, group in self.groups.items():
            group.title = PROFILES[key][0]
            group.pick, group.blocks = None, []
            group.main = list(group)
            if key in CONDITIONAL:
                pick, blocks = CONDITIONAL[key]
                held = {k for _, _, keys in blocks for k in keys}
                group.pick = group.add_prefix(pick)
                group.pick_value = group[pick].value() or ""
                group.main = [group[k] for k in group.fields if k not in held]
                group.blocks = [
                    (
                        title,
                        "[" + ",".join(f"'{o}'" for o in shows) + "]",
                        [group[k] for k in keys],
                    )
                    for title, shows, keys in blocks
                ]

    @property
    def profile(self):
        d = self.cleaned_data
        return profile_for(d.get("department"), d.get("sub_department"))

    def clean(self):
        data = super().clean()
        group = self.groups.get(self.profile)
        if group and not group.is_valid():
            self.add_error("sub_department", "Check the questions below.")
        return data

    def answers(self):
        got = super().answers()
        profile = self.profile
        who = got.pop("assessor", None)
        if who:
            got["assessor"], got["assessor_id"] = who.display_name, who.pk
        group = self.groups.get(profile)
        mine = group.answers() if group else {}
        if profile in CONDITIONAL:  # drop the list the candidate wasn't asked
            pick, blocks = CONDITIONAL[profile]
            for _, shows, keys in blocks:
                if mine.get(pick) not in shows:
                    mine = {k: v for k, v in mine.items() if k not in keys}
        return {**got, **mine}


class AssessmentForm(forms.Form):
    """HR's side (PFA). Decision and level are columns; the rest are answers."""

    use_required_attribute = False
    decision = forms.ChoiceField(
        label="Interview status",
        choices=[c for c in HRAssessment.decision.field.choices if c[0] != "pending"],
    )
    level = forms.ChoiceField(
        label="Level of candidate",
        choices=[("", "-"), *HRAssessment.Level.choices],
        required=False,
    )
    preference = forms.ChoiceField(
        label="Preference",
        choices=[("", "-"), *Person.Priority.choices],
        required=False,
    )
    comments = forms.CharField(
        label="PFA assessor comments",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key in PFA:
            self.fields[key] = whereabouts._field(key, SPEC)

    def clean(self):
        data = super().clean()
        if data.get("decision") == "hold" and "next_follow_up" not in self.errors:
            day = whereabouts.parse_day(data.get("next_follow_up"))
            if not day:
                message = "A candidate on hold needs a follow up date."
            elif day < timezone.localdate():
                message = "The follow up date can't be before today."
            else:
                message = ""
            if message:
                self.add_error("next_follow_up", message)
        return data

    def answers(self):
        """What goes in the JSON: everything but the two columns and the comments."""
        keep = {"preference", *PFA}
        got = {k: v for k, v in self.cleaned_data.items() if k in keep}
        return {k: v for k, v in got.items() if v not in ("", None, [])}
