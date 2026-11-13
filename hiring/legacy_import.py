"""One-off import of the old system's export (candidates, calls, assignments,
interviews, whereabout forms) into the hiring models.

`run()` does everything inside one transaction. A dry run rolls it back, so the
report shows exactly what a real run would do. Rows are written directly, not
through `source_number()`: importing must not book a call for every number.
See docs/superpowers/specs/2026-11-13-legacy-import-design.md for the rules."""

import csv
import difflib
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from core.models import Company
from people.models import Person, phone_key

from . import interview_form, whereabouts
from .models import (
    CallLog,
    FollowUp,
    HRAssessment,
    Interview,
    Offer,
    OfferRound,
    Requisition,
    SourcedNumber,
    day_start,
)
from .services import apply_to_person

csv.field_size_limit(10**9)

REQUISITION = "Data 13th Nov 26"
SOURCE = "Data 13th Nov 26"
BATCH = 5000
# A signature at the end of a note is a person when this many notes carry it.
MIN_SIGNATURES = 30

# The export marks "nothing" with this control character.
EMPTY = "\x0e"

# Logins of the old system -> the person. Anyone else is found by name.
ACCOUNTS = {
    "boavrishr@gmail.com": "Nitin",
    "boavrishr": "Nitin",
    "usha.p@senkenindia.in": "Usha P",
    "usha.p_senkenindia": "Usha P",
    "nishu.s@senkenindia.in": "Nishu",
    "nishu.s_senkenindia": "Nishu",
}
# Callers sign their notes ("... - nitin"). Spellings that are one person, and
# people who now go by another name.
ALIASES = {
    "muskaan": "muskan",
    "ansuhka": "anushka",
    "anushak": "anushka",
    "shlu": "shalu",
    "salu": "shalu",
    "taniy": "taniya",
    "ytaniya": "taniya",
    "nisu": "nishu",
    "nitn": "nitin",
    "amabala": "ambala",
    "pinky": "pratibha",
    "usha": "usha p",
    "nishu": "nishu",
    "nitin": "nitin",
    "rakshit": "rakshit sharma",
}
NOT_NAMES = {"both", "yes", "no", "na", "ok", "done", "call", "ringing"}
SIGNATURE = re.compile(r"[-–—]\s*([A-Za-z][A-Za-z .]{1,25}?)\s*\d*\.?\s*$")

# Notes that move or park calls in bulk: they are not calls, and are left out.
SHIFT = re.compile(
    r"shift|\bodb\b|hold kar|hold kra|calls? hold"
    r"|followups? (jyada|jyda|missing|lagaya)"
    r"|calls? (dedi|de di)|manpower|post odb"
    r"|saturday sab apna pending|cftl karva|ye data .* hold kiya|sunday ke din call",
    re.I,
)

OUTCOMES = {
    "Reg Call Touch": "reg_touch",
    "Reg Call Not Touch": "reg_not_touch",
    "Reg Call Not Attended": "reg_not_attended",
    "Reg F-F Interview": "reg_ff",
    "Reg T Interview": "reg_t",
    "WA Call Touch": "wa_touch",
    "WA Call Touch - DR": "wa_touch_dr",
    "WA Call Not Touch": "wa_not_touch",
    "WA Call Not Attended": "wa_not_attended",
    "WA F-F Interview": "wa_ff",
    "WA T Interview": "wa_t",
    "Update Touch": "update_touch",
    "Update Not Touch": "update_not_touch",
}

# Preference level -> (contact status, priority).
PREFERENCE = {
    "Close For Time Lapse": ("closed", ""),
    "ODB": ("on_demand", ""),
    "Do Not Call": ("do_not_call", ""),
    "Hold - FF": ("hold_ff", ""),
    "Open": ("active", ""),
    "Preferred": ("active", "preferred"),
    "Semi - preferred": ("active", "semi"),
    "Least - preferred": ("active", "least"),
}
# The date field also carried a status as a day in January 2000.
DATE_CODE = {
    "01": "closed",
    "03": "hold_ff",
    "04": "on_demand",
    "05": "joined",
    "06": "resigned",
    "07": "do_not_call",
}

PURPOSES = {
    "interview": FollowUp.Purpose.INTERVIEW,
    "offer": FollowUp.Purpose.OFFER,
    "joining": FollowUp.Purpose.JOINING,
    "update": FollowUp.Purpose.UPDATE,
    "assesment": FollowUp.Purpose.ASSESSMENT,
    "assessment": FollowUp.Purpose.ASSESSMENT,
}

DEPARTMENTS = {"bo", "training", "hr", "sales", "operations", "others"}
SUB_COLUMNS = {
    "bo": "BO_Sub_Department",
    "hr": "HR_Sub_Department",
    "operations": "Operations_Sub_Department",
    "sales": "Sales_Sub_Department",
    "training": "Training_Sub_Department",
    "others": "Others_Department_Before_Call",
}
SUB_COLUMNS_AFTER = {
    "bo": "BO_Sub_Department_After_Call",
    "hr": "HR_sub_Department_After_Call",
    "operations": "Operations_Sub_Department_After_Call",
    "sales": "Sales_Sub_Department_After_Call",
    "training": "Training_Sub_Department_After_Call",
    "others": "Others_Department_After_Call",
}

# What the interview form called a profile -> (department, sub-department).
INTERVIEW_PROFILES = {
    "Data Analyst/Data Executive": ("bo", "Data Analyst"),
    "HHE": ("operations", "HHE"),
    "BO": ("bo", "Back Office Executive"),
    "Elec + Mech": ("operations", "Elec + Mech"),
    "BO Cum Trainer": ("training", "Trainer"),
    "BO sales caller": ("sales", "Customer Sales Executive"),
    "BO Sales Caller": ("sales", "Customer Sales Executive"),
    "Helper": ("operations", "Helper"),
    "Helper Cum Welder": ("operations", "Welder"),
    "Sales Head / Sales Lead": ("sales", "Sales Head"),
    "Office Boy": ("bo", "Office Boy"),
}

ELEC = {
    "Wiring_Bunch": "elec_wiring_bunch",
    "Phase_connection_into_motor_encoder_connection": "elec_motor_encoder",
    "Junction_box_connection_filed_wiring_travelling_cable_connection_in_"
    "controller_with_ferul_thimble": "elec_junction_box",
    "Limit_fix_connections": "elec_limit",
    "Landing_doors_connections": "elec_landing_doors",
    "Reed_switch_fix_connections": "elec_reed_switch",
    "LOP_COP_Fix_connections": "elec_lop_cop",
    "Alarm_fireman_blower_fix_connections": "elec_alarm_blower",
    "Magnet_fix_levelling": "elec_magnet_levelling",
    "Hoist_Learning1": "elec_hoist_learning",
    "Car_Header_or_door_door_sensor_fix": "elec_car_header",
    "Door_drive_connections": "elec_door_drive",
    "Door_sensor_connections": "elec_door_sensor",
}
MECH = {
    "Reading_Marking": "mech_reading_marking",
    "Drilling_Bracket": "mech_drilling_bracket",
    "Guide_rails_hoisting": "mech_rails_hoisting",
    "Guide_rails_Alignment": "mech_rails_alignment",
    "Door_Frame": "mech_door_frame",
    "Landing_Door": "mech_landing_door",
    "Landing_Header": "mech_landing_header",
    "Motor_Alignment": "mech_motor_alignment",
    "Car_Counter_frame_alignment": "mech_car_counter_frame",
    "Roping": "mech_roping",
}

# Interview form column -> answer key (the yes/no skill lists are handled apart).
INTERVIEW_COLUMNS = {
    "Place_Of_Assessment": "place_of_assessment",
    "Place_of_Assessment_Others": "place_of_assessment_other",
    "Email": "email",
    "Temporary_Address": "temporary_address",
    "Previous_Temporary_Stays": "previous_temporary_stays",
    "Permanent_Address": "permanent_address",
    "Highest_Education": "highest_education",
    "Total_Experience_Months": "experience_months",
    "Departments_Worked_In": "departments_worked_in",
    "Last_CTC_including_conveyance_etc_Detailed": "last_ctc",
    "Expected_Salary_Monthly": "expected_salary",
    "Family": "family",
    "In_case_putting_up_away_from_family": "away_from_family",
    "Joining_Period_Days": "joining_days",
    "Place_Of_Birth1": "place_of_birth",
    "Date_Of_Birth": "date_of_birth",
    "Time_Of_Birth": "time_of_birth",
    "Alternate_No": "alternate_phone",
    "Date_field": "date",
}
# Answered in the old form but with no question of ours: kept, not shown.
INTERVIEW_EXTRA = {
    "Achievements_any_two": "Achievements (any two)",
    "Area_of_interest_and_Hobbies": "Area of interest and hobbies",
    "Internship": "Internship",
    "Placement": "Placement",
    "Duration_months": "Duration (months)",
    "Skills": "Skills",
    "Department1": "Department",
    "Cabin_Platform_fix_side_angle_fix_Safety_block_Shoe_fix": "Cabin platform fix",
}

# Whereabout column(s) -> answer key. Several columns can feed one key (one per
# department group in the old form); the first filled one wins.
MAJOR_COLUMNS = {
    "company_name": ["Company_Name"],
    "time_period_months": ["Time_Period_Months"],
    "designation": ["Designation"],
    "rfl": ["RFL"],
    "current_address": ["Current_Address"],
    "belongs_to": ["Belongs_to"],
    "last_ctc": ["Last_CTC_Monthly"],
    "in_hand_salary": ["In_Hand_Salary_Monthly"],
    "current_working_status": ["Current_Working_Status_Company_Name"],
    "joining_period_days": ["Joining_Period_Days"],
    "salary_expectation": ["Salary_Expectation_Monthly"],
    "affiliation": ["Affiliation_Previous_Present_Employee"],
    "family_details": ["Family_details_with_there_professions"],
    "lives_with": ["Kiske_sath_rhte_hn"],
    "trade": ["Elec_Mech1"],
    "multiple_sites": [
        "Multiple_Sites",
        "Multiple_Sites1",
        "Multiple_Sites2",
        "Multiple_Sites3",
    ],
    "conveyance": ["Conveyance_Monthly", "Conveyance_Monthly1", "Conveyance_Monthly2"],
    "leave": ["Leave", "Leave1", "Leave2"],
    "other_payments": [
        "Other_Payments",
        "Other_Payments1",
        "Other_Payments2",
        "Other_Payments3",
        "Other_Payments4",
    ],
    "g4_electrical": ["G_4_Electrical_completion_time_Ask_Questions"],
    "g4_installation": ["G_4_installation_completion_time_Ask_Questions"],
    "graduation": ["Graduation2", "Grduatoin", "Grduatoin1"],
    "arc_welding": ["ARK_Welding"],
    "pipe_welding": ["Pipe_Welding"],
    "multimeter": ["Multimeter_use_krna_aata_h"],
    "wiring_tracing": ["Wiring_tracing"],
    "iti_fitter": ["ITI_fitter"],
    "sales_other": [
        "Any_other_type_of_sales",
        "Any_other_type_of_sales1",
        "Any_other_type_of_sales2",
    ],
    "bike": ["Bike"],
    "public_speaking": ["Public_Speaking_topics"],
    "english_writing": ["Writing"],
    "english_speaking": ["Speaking"],
    "english_reading": ["Reading"],
    "school_12th": ["th_Schooling_Name"],
    "training": ["Training"],
    "profile": ["Profile"],
    "permanent_address": ["Permanent_Address"],
    "college": ["University_College_Name", "University_College_name1"],
    "study_department": ["Department1"],
    "graduation_course": ["Graduation_course_Specialization_if_any"],
    "post_graduation_course": ["Post_graduation_course_Specialization_if_any"],
    "diploma": ["Diploma_Specialization_if_any"],
    "other_course": ["Any_other_certified_course", "Any_other_certification_course"],
    "currently_pursuing": ["Currently_pursuing", "Currently_Pursuing1"],
    "study_year": ["Year_Completion_Final_Pre_final"],
    "internship_placement": ["Internship_Placement"],
    "duration": ["Duration"],
    "joining_date": ["Joining_Date"],
    "field_of_interest": ["Field_of_interest"],
    "websites_applied": ["Websites_applied"],
    "ms_office": [
        "Do_you_know_how_to_operate_basic_MS_Office_tools_like_MS_Word_MS_Excel"
    ],
    "course_branch": ["Course_Branch_if_any"],
    "year_completed": ["Year_Compeleted_in"],
    "excel_level": ["MS_Excel_Knowledge_Basic_or_Advanced"],
}
MINI_COLUMNS = {
    "current_company": ["Current_Company"],
    "total_experience_months": ["Total_Experience_Months"],
    "joining_period_days": ["Joining_Period_Days"],
    "current_address": ["Current_Address"],
    "current_salary": ["Current_Salary_Monthly"],
    "availability_status": ["Availability_Status"],
    "notes": ["Notes"],
}
# The old form's department names that differ from ours.
DEPARTMENT_GROUPS = {
    "Data Analyst / Data Executive": "analyst",
    "BO sales caller": "bo_caller",
}


# ---------------------------------------------------------------- reading


def unpack(archive, into):
    """The export is a zip of zips: returns (folder of csv files, folder of files)."""
    into = Path(into)
    with zipfile.ZipFile(archive) as z:
        z.extractall(into)
    for inner in list(into.rglob("*.zip")):
        with zipfile.ZipFile(inner) as z:
            z.extractall(inner.with_suffix(""))
    data = next(p for p in into.rglob("basic#Candidate_Master.csv")).parent
    files = next(
        (p.parent.parent for p in into.rglob("Interviews") if p.is_dir()), into
    )
    return data, files


class Row(dict):
    """A csv row; a column the export doesn't have reads as blank."""

    def __missing__(self, key):
        return ""


def table(folder, name):
    """Rows of one csv as dicts. The export escapes quotes with a backslash."""
    with open(Path(folder) / name, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f, escapechar="\\"))
    head = rows[0]
    return [
        Row((k, "" if v == EMPTY else v) for k, v in zip(head, r, strict=False))
        for r in rows[1:]
        if r
    ]


def links(folder, name):
    """Link file: row id -> the id it points to (one target per row)."""
    with open(Path(folder) / name, newline="", encoding="utf-8-sig") as f:
        return {r[0]: r[1] for r in list(csv.reader(f))[1:] if len(r) > 1}


def ts(ms):
    """Milliseconds since 1970 as a datetime, or None."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def text(value):
    value = (value or "").strip()
    return "" if value.upper() in ("NA", "N/A", "0") else value


def number(value):
    """A positive amount, or None (the old system saved 0 for "not known")."""
    try:
        n = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return n if n > 0 else None


def whole(value):
    n = number(value)
    return int(n) if n is not None else None


def day(value):
    return whereabouts.parse_day((value or "").strip()[:10])


def yesno(value):
    v = (value or "").strip().lower()
    return (
        "Yes"
        if v in ("yes", "true", "y")
        else "No"
        if v in ("no", "false", "n")
        else ""
    )


def numbers(raw):
    """The phone numbers in a field: "9876543210/9811122233" gives two."""
    parts = re.split(r"[/,;\n&]| or ", raw or "")
    return [p.strip() for p in parts if len(re.sub(r"\D", "", p)) >= 5]


def sub_department(row, department, columns):
    return text(row.get(columns.get(department, ""), ""))


def department_of(row, which):
    """(department key, sub-department) for the card, before or after the call."""
    after = which == "after"
    key = text(row.get("Department_After_Call" if after else "Department")).lower()
    columns = SUB_COLUMNS_AFTER if after else SUB_COLUMNS
    others = text(row.get(columns["others"]))
    if key not in DEPARTMENTS:
        key = "others" if others else ""
    return key, sub_department(row, key, columns)


# ----------------------------------------------------------------- people


class Users:
    """Finds the ERP user for a name or an old login. Someone with no account
    gets an inactive one, shown everywhere as a former employee."""

    def __init__(self):
        self.model = get_user_model()
        self.cache, self.created, self.found = {}, [], {}
        self.known = set()  # signatures common enough to be a person

    def named(self, name):
        key = name.strip().lower()
        if key in self.cache:
            return self.cache[key]
        users = list(self.model.objects.order_by("-is_active", "pk"))
        match = next(
            (
                u
                for u in users
                if key in (u.first_name.lower(), u.get_full_name().lower())
            ),
            None,
        )
        if match:
            self.found[name] = match
        else:
            base = f"OLD-{re.sub(r'[^a-z0-9]+', '-', key).strip('-').upper()}"
            taken = set(
                self.model.objects.filter(username__startswith=base).values_list(
                    "username", flat=True
                )
            )
            username, n = base, 1
            while username in taken:
                n += 1
                username = f"{base}-{n}"
            match = self.model(
                username=username,
                first_name=name.title(),
                is_active=False,
                must_change_password=False,
            )
            match.set_unusable_password()
            match.save()
            self.created.append(name)
        self.cache[key] = match
        return match

    def account(self, login):
        login = (login or "").removeprefix("Z:").strip().lower()
        return self.named(ACCOUNTS[login]) if login in ACCOUNTS else None

    def signed(self, note):
        """The caller named at the end of a note: a common signature, or the
        nearest one to a misspelling. None when it isn't a name."""
        name = raw_signature(note)
        if not name or name in self.known:
            return name or None
        close = difflib.get_close_matches(name, self.known, n=1, cutoff=0.8)
        return close[0] if close else None


def raw_signature(note):
    m = SIGNATURE.search((note or "").strip())
    if not m:
        return None
    name = m.group(1).strip().lower().rstrip(".")
    name = ALIASES.get(name, name)
    return None if name in NOT_NAMES else name


def person_row(row):
    """The fields of a card from a candidate master row."""
    # Every number on its own field: phone, alternate phone, phone 3, phone 4.
    # The Alternate No column comes second, then the rest of the Phone No field.
    numbered = numbers(row["Phone_No"])
    first = numbered[0] if numbered else row["Phone_No"].strip()
    alt = text(row["Alternate_No"])
    ordered = [first]
    for n in [alt if len(phone_key(alt)) >= 10 else "", *numbered[1:]]:
        if n and phone_key(n) not in {phone_key(o) for o in ordered}:
            ordered.append(n)
    phone, alt, third, fourth = [*ordered[:4], "", "", ""][:4]
    pref = PREFERENCE.get(row["Preference_Level"].strip(), ("active", ""))
    status, priority = pref
    if status == "active" and "Hold - FF" in (
        row["Hiring_Stage"],
        row["Interview_Status"],
    ):
        status = "hold_ff"
    dept, sub = department_of(row, "before")
    dept2, sub2 = department_of(row, "after")
    months = whole(row["Total_Experience_Months"])
    created = ts(row["Added_Time"])
    gender = {"Male": "M", "Female": "F"}.get(row["Gender"].strip(), "")
    return dict(
        name=row["Name"].strip()[:200],
        phone=phone[:30],
        phone_key=phone_key(phone),
        alternate_phone=alt[:30],
        phone_3=third[:30],
        phone_4=fourth[:30],
        gender=gender,
        address=text(row["Temporary_Address"]),
        permanent_address=text(row["Permanent_Address"]),
        current_salary=number(row["Previous_Salary_Monthly"]),
        expected_salary=number(row["Expected_Salary_Monthly"]),
        experience_years=round(months / 12, 1) if months else None,
        contact_status=status,
        priority=priority,
        candidate_id=row["Candidate_ID"].strip(),
        legacy_id=text(row["Legacy_ID"])[:40],
        department=dept,
        sub_department=sub[:120],
        department_after_call=dept2,
        sub_department_after_call=sub2[:120],
        source_reference=text(row["Source_Reference"])[:200],
        source_keyword=text(row["Source_Keyword"])[:200],
        payment={"Free": "Free", "Paid": "Paid"}.get(row["Paid_Free"].strip(), ""),
        belongs_to=text(row["Belongs_to"])[:200],
        lead_received_on=day(row["Lead_Received_Date"]),
        repeated={"Yes": "Yes", "No": "No"}.get(row["Repeated"].strip(), ""),
        reference_generated_by=text(row["Reference_Generated_By"])[:200],
        skills=text(row["Skills_Observed"]),
        assessor_comments=text(row["Assessor_Comments"]),
        resignation_on=day(row["Resignation_Date"]),
        resignation_reason=text(row["Resignation_Reason"]),
        created_at=created or timezone.now(),
    )


# ------------------------------------------------------------ whereabouts


def coerce(kind, value):
    """An answer in the form `kind` expects, or None when it doesn't fit (the old
    form took free text where ours takes a choice)."""
    value = (value or "").strip()
    if kind == "yesno":
        return yesno(value) or None
    if kind == "int":
        return whole(value)
    if kind == "rate":
        return value if value in {"1", "2", "3", "4", "5"} else None
    if kind == "date":
        d = day(value)
        return d.isoformat() if d else None
    if kind.startswith(("choice:", "multi:")):
        options = kind.split(":")[1].split("|")
        return next((o for o in options if o.lower() == value.lower()), None)
    return text(value) or None


def whereabout_answers(row, columns):
    out = {}
    for key, cols in columns.items():
        kind = whereabouts.SPEC[key][0]
        for col in cols:
            got = coerce(kind, row.get(col))
            if got is not None:
                out[key] = got
                break
    return out


def major_answers(row):
    out = whereabout_answers(row, MAJOR_COLUMNS)
    label = row.get("Department", "").strip()
    group = DEPARTMENT_GROUPS.get(label) or next(
        (k for k, g in whereabouts.GROUPS.items() if g[0] == label), None
    )
    if group:
        out["department"] = group
    # Only the questions of the chosen group (and the common ones) belong here.
    allowed = set(whereabouts.COMMON) | set(whereabouts.GROUPS.get(group, (0, []))[1])
    return {k: v for k, v in out.items() if k in allowed or k == "department"}


# -------------------------------------------------------------- interviews


def months_of(duration):
    """ "2 Years 4 Months" -> "28"."""
    m = re.match(r"\s*(\d+)\s*Years?\s*(\d+)\s*Months?", duration or "", re.I)
    return str(int(m[1]) * 12 + int(m[2])) if m else ""


def subform(folder, rows_name, link_name, interview_ids):
    """The rows of a table inside an interview: interview id -> [row, ...]."""
    by_id = {r["ID"]: r for r in table(folder, rows_name)}
    out = defaultdict(list)
    for base, ref in links(folder, link_name).items():
        if base in interview_ids and ref in by_id:
            out[base].append(by_id[ref])
    return out


def interview_answers(row, vehicles, work, education, user):
    dept, sub = INTERVIEW_PROFILES.get(row["Profile"].strip(), ("", ""))
    a = {"department": dept, "sub_department": sub} if dept else {}
    for col, key in INTERVIEW_COLUMNS.items():
        got = coerce(interview_form.SPEC[key][0], row.get(col))
        if got is not None:
            a[key] = got
    if user:
        a["assessor"], a["assessor_id"] = user.display_name, user.pk
    elec = {k: row.get(c) == "true" for c, k in ELEC.items()}
    mech = {k: row.get(c) == "true" for c, k in MECH.items()}
    if any(elec.values()) or any(mech.values()):
        a["trade"] = (
            "Both"
            if any(elec.values()) and any(mech.values())
            else "Electrical"
            if any(elec.values())
            else "Mechanical"
        )
        a.update({k: "Yes" for k, v in {**elec, **mech}.items() if v})
    a["vehicle_status"] = "Has a vehicle" if vehicles else "No vehicle"
    a["vehicles"] = [
        {
            "vehicle": v["Vehicle"],
            "own": yesno(v["Own"]),
            "driving": yesno(v["Driving_Status"]),
            "dl": v["DL_Status"],
        }
        for v in vehicles
    ]
    a["work"] = [
        {
            "place": w["Place_Of_Duty"],
            "organization": w["Name_Of_Organization"],
            "start": w["Start_Date"],
            "current": yesno(w["Currently_Working"]),
            "end": w["End_Date"],
            "duration": months_of(w["Duration"]),
            "does": w["What_Organization_Does"],
            "role": w["What_was_your_role_in_the_organization"],
            "salary": str(whole(w["Salary_Monthly"]) or ""),
            "rfl": w["RFL"],
        }
        for w in work
    ]
    a["education"] = [
        {
            "qualification": e["Academic_Qualification"],
            "board": e["Board_University"],
            "school": e["School_College_Name"],
            "year": e["Pass_out_year"],
            "course": e["Course"],
            "specialization": e["Specialization_if_any"],
            "grade": e["CGPA_Percentage_Grade"],
        }
        for e in education
    ]
    extra = {
        label: row[col].strip()
        for col, label in INTERVIEW_EXTRA.items()
        if text(row[col])
    }
    if extra:
        a["other"] = extra
    return a


def hr_answers(row):
    a = {
        "skills": text(row["Skills_After_Interview"]),
        "offer_given": whole(row["Offer_given_if_any"]),
        "salary_discussion": text(row["Expected_salary_discussion"]),
        "unique_id": text(row["Unique_identification"]),
        "questions_asked": text(row["Questions_Asked"]),
        "next_follow_up": str(day(row["Next_Follow_Up_Date"]) or ""),
        "hr_form_submitted": yesno(row["HR_form_submitted"]),
        "closed": yesno(row["Interview_closed"]),
        "closed_reason": text(row["Interview_closed_reason"]),
        "preference": {
            "Preferred": "preferred",
            "Semi - preferred": "semi",
            "Least - preferred": "least",
        }.get(row["Preference"].strip(), ""),
    }
    return {k: v for k, v in a.items() if v not in ("", None)}


def find_file(folder, kind, prefix=None, name=None):
    base = Path(folder) / "Interviews" / kind
    if name:
        path = base / name
        return path if path.is_file() else None
    return next(iter(sorted(base.glob(f"{prefix}_*"))), None) if base.is_dir() else None


# ------------------------------------------------------------------- dates


@contextmanager
def keep_dates(*pairs):
    """Let rows keep the dates they come with: `auto_now_add` would stamp today."""
    fields = [m._meta.get_field(n) for m, n in pairs]
    old = [f.auto_now_add for f in fields]
    for f in fields:
        f.auto_now_add = False
    try:
        yield
    finally:
        for f, o in zip(fields, old, strict=True):
            f.auto_now_add = o


class DryRun(Exception):
    """Raised at the end of a dry run to roll everything back."""


# --------------------------------------------------------------------- run


def run(data, files, apply=False, log=print):
    """Import. Returns a dict of counts and review rows; writes nothing when
    `apply` is false."""
    stats, review, saved = Counter(), [], []
    try:
        with transaction.atomic():
            _run(data, files, apply, stats, review, log, saved)
            if not apply:
                raise DryRun
    except DryRun:
        pass
    except Exception:
        # The database rolls back; files already copied to storage must go too.
        for name in saved:
            default_storage.delete(name)
        raise
    return stats, review


def _run(data, files, apply, stats, review, log, saved):
    if Requisition.objects.filter(profile=REQUISITION).exists():
        raise RuntimeError("Candidates were already imported; run it only once.")
    company = Company.objects.get(slug="senken")
    users = Users()
    nitin = users.named("Nitin")

    cards = table(data, "basic#Candidate_Master.csv")
    ids = [r["Candidate_ID"].strip() for r in cards if r["Candidate_ID"].strip()]
    clash = {i for i, n in Counter(ids).items() if n > 1} | set(
        Person.objects.filter(candidate_id__in=ids).values_list(
            "candidate_id", flat=True
        )
    )
    if clash:
        raise RuntimeError(
            f"{len(clash)} candidate ids are used twice (in the file or already "
            f"in the ERP), for example {sorted(clash)[:5]}"
        )
    by_zid = {r["ID"]: r for r in cards}
    log_of = links(data, "rel#Candidate#Call_Logs.csv")
    calls = [r for r in table(data, "basic#Call_Logs.csv") if r["ID"] in log_of]
    stats["call logs in file"] = len(calls)
    log(f"read {len(cards)} candidates, {len(calls)} call logs")

    # --- who is the main card of each phone number: a card already in the ERP,
    # else the one with the most call logs. The others stay, archived.
    per_card_logs = Counter(log_of[c["ID"]] for c in calls)
    groups, group_of = defaultdict(list), {}
    for r in cards:
        key = phone_key((numbers(r["Phone_No"]) or [""])[0])
        key = key if len(key) == 10 else f"solo-{r['ID']}"
        groups[key].append(r)
        group_of[r["ID"]] = key
    existing = {}
    for p in Person.objects.filter(company=company, archived_at__isnull=True).order_by(
        "pk"
    ):
        existing[p.phone_key] = p

    def live(r):
        """A dated call on a card that may be called must stay callable."""
        due = day(r["Next_Follow_Up_Date"])
        status = PREFERENCE.get(r["Preference_Level"].strip(), ("active", ""))[0]
        return bool(due and due.year >= 2020 and status == "active")

    best = {
        key: max(
            members,
            key=lambda r: (
                live(r),
                per_card_logs[r["ID"]],
                whole(r["Candidate_Serial_Number"]) or 0,
            ),
        )["ID"]
        for key, members in groups.items()
    }
    stats["numbers on more than one card"] = sum(len(m) > 1 for m in groups.values())
    stats["numbers already on a card in the ERP"] = sum(k in existing for k in groups)

    # --- requisition
    requisition = Requisition.objects.create(
        company=company,
        department="others",
        profile=REQUISITION,
        headcount=max(len(cards), 1),
        status=Requisition.Status.CLOSED,
        opened_by=nitin,
        other_details="Everyone imported from the old system on 13 Nov 2026.",
    )

    # --- people
    now = timezone.now()
    rows = []
    for r in cards:
        fields = person_row(r)
        fields["company"] = company
        if r["ID"] != best[group_of[r["ID"]]] or group_of[r["ID"]] in existing:
            fields["archived_at"] = now
        rows.append(Person(**fields))
        if len(numbers(r["Phone_No"])) > 4 or len(phone_key(fields["phone"])) < 10:
            review.append(
                (
                    "phone too short or more than four numbers",
                    r["Candidate_ID"],
                    r["Phone_No"],
                )
            )
        if fields["alternate_phone"]:
            stats["cards with a second number"] += 1
        if fields["phone_3"]:
            stats["cards with a third number"] += 1
    with keep_dates((Person, "created_at")):
        Person.objects.bulk_create(rows, batch_size=BATCH)
    person_of = {r["ID"]: p for r, p in zip(cards, rows, strict=True)}
    stats["cards"] = len(rows)
    stats["cards archived (not the main card of their number)"] = sum(
        1 for p in rows if p.archived_at
    )
    main_card = {
        zid: existing.get(group_of[zid]) or person_of[best[group_of[zid]]]
        for zid in person_of
    }
    log("cards written")

    # --- sourced numbers, one per card
    sourced = []
    for r in cards:
        when = day(r["Lead_Received_Date"])
        made = day_start(when) if when else ts(r["Added_Time"]) or now
        sourced.append(
            SourcedNumber(
                requisition=requisition,
                person=person_of[r["ID"]],
                source=SOURCE,
                is_duplicate=person_of[r["ID"]].archived_at is not None,
                sourced_by=nitin,
                created_at=made,
            )
        )
    with keep_dates((SourcedNumber, "created_at")):
        SourcedNumber.objects.bulk_create(sourced, batch_size=BATCH)
    stats["sourced numbers"] = len(sourced)
    stats["  of them duplicates"] = sum(s.is_duplicate for s in sourced)

    # --- calls
    signatures = Counter(raw_signature(r["Status"]) for r in calls)
    users.known = {n for n, c in signatures.items() if n and c >= MIN_SIGNATURES}
    call_objs, flagged = [], defaultdict(list)
    shifted, shift_notes, other_notes = 0, Counter(), Counter()
    unmapped = Counter()
    for r in calls:
        zid = log_of[r["ID"]]
        note = r["Status"].strip()
        who = users.signed(note)
        caller = (
            users.named(who)
            if who
            else users.account(r["Call_made_by"] or r["Added_User"]) or nitin
        )
        tag = r["Tagging"].strip()
        outcome = OUTCOMES.get(tag, "blank")
        if tag not in OUTCOMES and tag != "Blank":
            unmapped[tag[:40]] += 1
        kind = r["Call_Type"].strip()
        # A log carrying a whereabout form is kept whatever its note says.
        left_out = (
            not kind
            and bool(SHIFT.search(note))
            and r["Major_Whereabout"] != "true"
            and r["Mini_Whereabout"] != "true"
        )
        if left_out:
            shifted += 1
            shift_notes[SHIFT_KEY.sub("", note.lower())[:90]] += 1
            continue
        when = ts(r["Call_Date"]) or ts(r["Added_Time"]) or now
        added = ts(r["Added_Time"])
        if when > (added or now):  # a call can't be dated after it was logged
            when = added or now
        if not ts(r["Call_Date"]) and not added:
            review.append(("call log without a date, dated today", zid, note[:60]))
        c = CallLog(
            person=person_of[zid],
            caller=caller,
            called_at=when,
            outcome=outcome,
            notes=note,
            call_type="inbound" if kind == "Incoming" else "outbound",
            discussed=kind == "Discuss with Manager" or r["Discuss_with_sir"] == "true",
        )
        call_objs.append(c)
        other_notes[SHIFT_KEY.sub("", note.lower())[:90]] += 1
        for flag in ("Major_Whereabout", "Mini_Whereabout"):
            if r[flag] == "true":
                flagged[(zid, flag)].append((added or when, c))
    stats["call logs"] = len(call_objs)
    stats["call logs left out (shifts and parking)"] = shifted
    for tag, n in unmapped.items():
        review.append(("call tag not recognised, saved as Blank", tag, n))

    # --- whereabout forms: onto a call flagged for it, else a call of their own
    for flag, name, link, columns, build in (
        (
            "Major_Whereabout",
            "basic#Major_Whereabout.csv",
            "rel#Candidate2#Major_Whereabout.csv",
            None,
            major_answers,
        ),
        (
            "Mini_Whereabout",
            "basic#Mini_Whereabout.csv",
            "rel#Candidate#Mini_Whereabout.csv",
            MINI_COLUMNS,
            None,
        ),
    ):
        owner = links(data, link)
        for w in sorted(table(data, name), key=lambda x: x["Added_Time"]):
            zid = owner.get(w["ID"])
            if zid not in person_of:
                continue
            answers = build(w) if build else whereabout_answers(w, columns)
            if not answers:
                continue
            slot = (
                "major_whereabout" if flag == "Major_Whereabout" else "mini_whereabout"
            )
            at = ts(w["Added_Time"]) or now
            home = main_card[zid]
            near = [
                (abs((t - at).total_seconds()), i, c)
                for i, (t, c) in enumerate(flagged[(zid, flag)])
                if c.person is home and not getattr(c, slot)
            ]
            if near:
                setattr(min(near, key=lambda x: x[:2])[2], slot, answers)
                stats[f"{slot.split('_')[0]} forms on their call"] += 1
            else:
                stand = CallLog(
                    person=home,
                    caller=users.account(w["Added_User"]) or nitin,
                    called_at=at,
                    outcome="blank",
                    notes="Whereabout form (imported)",
                    **{slot: answers},
                )
                call_objs.append(stand)
                stats[f"{slot.split('_')[0]} forms as a call of their own"] += 1
    with keep_dates((CallLog, "called_at")):
        CallLog.objects.bulk_create(call_objs, batch_size=BATCH)
    log("calls written")

    # --- assignments that were made and done
    done = []
    assigned = links(data, "rel#Candidate#Call_Assignment.csv")
    for a in table(data, "basic#Call_Assignment.csv"):
        zid = assigned.get(a["ID"])
        if (
            zid not in person_of
            or not day(a["Date_field"])
            or a["Status"] != "Completed"
        ):
            continue
        owner = users.account(a["Assigned_To"]) or nitin
        original = day(a["Original_Date"])
        due = day(a["Date_field"])
        done.append(
            FollowUp(
                person=person_of[zid],
                requisition=requisition,
                due=day_start(due),
                original_due=day_start(original)
                if original and original != due
                else None,
                owner=owner,
                status="completed",
                created_at=ts(a["Added_Time"]) or now,
            )
        )
    with keep_dates((FollowUp, "created_at")):
        FollowUp.objects.bulk_create(done, batch_size=BATCH)
    stats["assignments (done)"] = len(done)

    # --- pending calls, at most one per number, on the main card
    wanted = {}
    for r in cards:
        due = day(r["Next_Follow_Up_Date"])
        if not due or due.year < 2020:
            continue
        zid = r["ID"]
        home = main_card[zid]
        if home.contact_status != "active" or home.archived_at:
            own = person_of[zid].contact_status
            review.append(
                (
                    f"dated call, but the card is marked {home.contact_status}"
                    if own == home.contact_status
                    else "dated call, but the main card of its number is marked "
                    + home.contact_status,
                    r["Candidate_ID"],
                    r["Next_Follow_Up_Date"],
                )
            )
            continue
        seen = wanted.get(home.pk)
        if seen:
            # The earlier date is kept; the other is listed as dropped.
            lost = r if due >= seen[0] else seen[1]
            review.append(
                (
                    "second dated call for the same number, dropped",
                    lost["Candidate_ID"],
                    lost["Next_Follow_Up_Date"],
                )
            )
            if due >= seen[0]:
                continue
        wanted[home.pk] = (due, r, home)
    waiting = set(
        FollowUp.objects.filter(status="pending", person_id__in=wanted).values_list(
            "person_id", flat=True
        )
    )
    pending = []
    for pk, (due, r, home) in wanted.items():
        if pk in waiting:
            review.append(
                ("card already has a call waiting, kept", r["Candidate_ID"], "")
            )
            continue
        pending.append(
            FollowUp(
                person=home,
                requisition=requisition,
                purpose=PURPOSES.get(
                    r["Call_Type"].strip().lower(), FollowUp.Purpose.CALL
                ),
                due=day_start(due),
                owner=users.account(r["Assigned_To"]) or nitin,
                reschedule_count=whole(r["Reschedule_Count_CM"]) or 0,
                created_at=ts(r["Added_Time"]) or now,
            )
        )
        if not r["Assigned_To"].strip():
            stats["pending calls given to Nitin (nobody was assigned)"] += 1
        if day_start(due) < timezone.now():
            stats["pending calls already overdue"] += 1
    with keep_dates((FollowUp, "created_at")):
        FollowUp.objects.bulk_create(pending, batch_size=BATCH)
    stats["pending calls"] = len(pending)
    log("follow-ups written")

    # --- interviews and their forms
    ivs = table(data, "basic#Interviews.csv")
    iv_owner = links(data, "rel#Candidate#Interviews.csv")
    ids = {i["ID"] for i in ivs}
    vehicles = subform(
        data,
        "basic#Vehicle_Status@Interviews.csv",
        "rel#Vehicle_Status#Interviews.csv",
        ids,
    )
    work = subform(
        data,
        "basic#Work_Experience@Interviews.csv",
        "rel#Work_Experience#Interviews.csv",
        ids,
    )
    schooling = subform(
        data,
        "basic#Educational_Background@Interviews.csv",
        "rel#Educational_Background#Interviews.csv",
        ids,
    )
    for i in ivs:
        zid = iv_owner.get(i["ID"])
        if zid not in person_of:
            continue
        home = main_card[zid]
        user = users.account(i["Assessor"]) or users.account(i["Added_User"]) or nitin
        result = {"Select": "selected", "Hold": "hold"}.get(
            i["Interview_Status"].strip(), "pending"
        )
        dept, sub = INTERVIEW_PROFILES.get(i["Profile"].strip(), ("", ""))
        when = day(i["Date_field"])
        if phone_key(i["Phone_Number"]) != person_of[zid].phone_key:
            review.append(
                (
                    "interview phone differs from the card",
                    by_zid[zid]["Candidate_ID"],
                    i["Phone_Number"],
                )
            )
        with keep_dates((Interview, "created_at"), (HRAssessment, "created_at")):
            iv = Interview.objects.create(
                person=home,
                requisition=requisition,
                scheduled_at=day_start(when) if when else ts(i["Added_Time"]) or now,
                result=result,
                questions=text(i["Questions_Asked"]),
                profile=interview_form.profile_for(dept, sub),
                answers=interview_answers(
                    i, vehicles[i["ID"]], work[i["ID"]], schooling[i["ID"]], user
                ),
                interviewer=user,
                created_at=ts(i["Added_Time"]) or now,
            )
            stats["interviews"] += 1
            hr = None
            if result != "pending":
                hr = HRAssessment.objects.create(
                    interview=iv,
                    decision=result,
                    level=i["Level_of_Candidate"].strip().lower()
                    if i["Level_of_Candidate"].strip().lower()
                    in ("expert", "intermediate", "beginner", "helper")
                    else "",
                    hold_tenure=text(i["Hold_Tenure"])[:60],
                    comments=text(i["PFA_Assessor_Comments"]),
                    answers=hr_answers(i),
                    assessor=user,
                    created_at=ts(i["Modified_Time"]) or now,
                )
                stats["HR assessments"] += 1
        # The interview wins where it and the card disagree.
        apply_to_person(iv, hr and hr.answers.get("preference"))
        if apply:
            _attach_files(iv, i, files, saved)

    # --- offers: people the old system had offered or taken on
    for r in cards:
        stage = r["Hiring_Stage"].strip()
        if stage not in ("Offered", "Joined"):
            continue
        home = main_card[r["ID"]]
        amount = number(r["Offered_Salary_Monthly"])
        joining = day(r["Joining_Date"])
        if not amount or (stage == "Joined" and not joining):
            review.append(
                (f"{stage} but no amount or date, no offer made", r["Candidate_ID"], "")
            )
            continue
        if home.offers.filter(state__in=["offered", "accepted"]).exists():
            continue
        with keep_dates((Offer, "created_at"), (OfferRound, "created_at")):
            offer = Offer.objects.create(
                person=home,
                requisition=requisition,
                state="accepted" if stage == "Joined" else "offered",
                joining_date=joining if stage == "Joined" else None,
                joined_on=joining if stage == "Joined" else None,
                decided_at=day_start(joining) if stage == "Joined" else None,
                made_by=nitin,
                created_at=ts(r["Modified_Time"]) or now,
            )
            OfferRound.objects.create(
                offer=offer, amount=amount, by=nitin, created_at=offer.created_at
            )
        stats[f"offers ({stage.lower()})"] += 1

    # --- things to look at
    for r in cards:
        if r["Next_Follow_Up_Date"].startswith("2000-01-"):
            code = DATE_CODE.get(r["Next_Follow_Up_Date"][-2:])
            want = PREFERENCE.get(r["Preference_Level"].strip(), ("active", ""))[0]
            if code and code != want:
                review.append(
                    (f"date says {code}, preference says {want}", r["Candidate_ID"], "")
                )
    stats["names matched to existing users"] = len(users.found)
    stats["names with no account (now former employees)"] = len(users.created)
    stats["_matched"] = {k: v.display_name for k, v in users.found.items()}
    stats["_created"] = users.created
    stats["_shift_notes"] = shift_notes.most_common(25)
    stats["_other_notes"] = other_notes.most_common(25)


SHIFT_KEY = re.compile(r"\s*[-–—]\s*[a-z .]{2,25}\d*$")


def _attach_files(interview, row, files, saved):
    resume = (
        find_file(files, "Resume", name=row["Resume"].strip())
        if row["Resume"].strip()
        else None
    )
    photo_id = re.search(r"(\d{10,})_\d+", row["Image"] or "")
    photo = find_file(files, "Image", prefix=photo_id[1]) if photo_id else None
    for field, path in ((interview.resume, resume), (interview.photo, photo)):
        if path:
            with open(path, "rb") as f:
                field.save(path.name, File(f), save=False)
            saved.append(field.name)
    interview.save(update_fields=["resume", "photo"])


def from_archive(archive, apply=False, log=print):
    with tempfile.TemporaryDirectory() as tmp:
        data, files = unpack(archive, tmp)
        return run(data, files, apply=apply, log=log)
