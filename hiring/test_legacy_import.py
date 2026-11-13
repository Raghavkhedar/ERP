import csv
import os
from datetime import date, timedelta

import pytest
from django.utils import timezone

from core.models import Company
from people.models import Person

from . import legacy_import
from .models import CallLog, FollowUp, HRAssessment, Interview, SourcedNumber

pytestmark = pytest.mark.django_db

MS = 1_786_437_903_000  # 11 Aug 2026
NEXT = (timezone.localdate() + timedelta(days=5)).isoformat()


def write(folder, name, rows):
    """Rows are dicts; the header is every key used."""
    head = list({k: 1 for r in rows for k in r})
    with open(folder / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows([r.get(k, "") for k in head] for r in rows)


def link(folder, name, pairs):
    with open(folder / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["base", "ref"])
        w.writerows(pairs)


def card(n, **kw):
    return {
        "ID": f"z{n}",
        "Candidate_ID": f"WJ{n}",
        "Candidate_Serial_Number": str(n),
        "Name": f"Person {n}",
        "Phone_No": f"98765432{n:02d}",
        "Added_Time": str(MS),
        "Preference_Level": "Open",
        "Department": "Operations",
        "Operations_Sub_Department": "Elec + Mech",
        "Source_Reference": "Indeed",
        **kw,
    }


@pytest.fixture
def export(tmp_path):
    d = tmp_path
    cards = [
        # a number on two cards: the one with more calls leads
        card(1, Phone_No="9876543201/9811100001"),
        card(2, Phone_No="9876543201"),
        # a dated call with an assignee, then one with none
        card(
            3,
            Next_Follow_Up_Date=NEXT,
            Assigned_To="Z:nishu.s@senkenindia.in",
            Phone_No="9876543203 / 9811100003, 9811100004;9811100005",
            Alternate_No="9811100009",
        ),
        card(4, Next_Follow_Up_Date=NEXT, Call_Type="Interview"),
        # a status code: the preference is the truth, the date goes
        card(
            5,
            Next_Follow_Up_Date="2000-01-04",
            Preference_Level="ODB",
            Assigned_To="Z:nishu.s@senkenindia.in",
        ),
        card(
            6,
            Preference_Level="Semi - preferred",
            Department="BO",
            BO_Sub_Department="Data Analyst",
            Operations_Sub_Department="NA",
        ),
    ]
    write(d, "basic#Candidate_Master.csv", cards)
    logs = [
        {
            "ID": "l1",
            "Added_Time": str(MS),
            "Call_Date": str(MS),
            "Call_Type": "Outgoing",
            "Call_made_by": "boavrishr",
            "Status": "ringing-taniya",
            "Tagging": "Reg Call Not Touch",
            "Major_Whereabout": "true",
        },
        {
            "ID": "l2",
            "Added_Time": str(MS),
            "Call_Date": str(MS - 86_400_000),
            "Status": "sabko calls dedi hai ye calls extra hai isiliye shift kr rhi hu",
            "Tagging": "Reg Call Touch",
        },
        {
            "ID": "l3",
            "Added_Time": str(MS),
            "Call_Date": str(MS - 5 * 86_400_000),
            "Status": "ringing - taniya",
            "Tagging": "Blank",
        },
        {
            "ID": "l4",
            "Added_Time": str(MS),
            "Call_Date": str(MS),
            "Call_Type": "Discuss with Manager",
            "Call_made_by": "usha.p_senkenindia",
            "Status": "wants to talk",
            "Tagging": "Reg F-F Interview",
        },
        {
            "ID": "l5",
            "Added_Time": str(MS),
            "Call_Date": str(MS),
            "Status": "busy - taniya",
        },
        {"ID": "orphan", "Added_Time": str(MS), "Status": "no card"},
    ]
    write(d, "basic#Call_Logs.csv", logs)
    # card 2 holds the calls, so it leads number ...01
    link(
        d,
        "rel#Candidate#Call_Logs.csv",
        [("l1", "z2"), ("l2", "z2"), ("l3", "z2"), ("l4", "z3"), ("l5", "z2")],
    )
    write(
        d,
        "basic#Call_Assignment.csv",
        [
            {
                "ID": "a1",
                "Date_field": "2026-08-11",
                "Original_Date": "2026-08-10",
                "Assigned_To": "Z:nishu.s@senkenindia.in",
                "Status": "Completed",
                "Added_Time": str(MS),
            },
        ],
    )
    link(d, "rel#Candidate#Call_Assignment.csv", [("a1", "z3")])
    write(
        d,
        "basic#Major_Whereabout.csv",
        [
            {
                "ID": "m1",
                "Added_Time": str(MS),
                "Added_User": "Z:nishu.s@senkenindia.in",
                "Department": "Elec + Mech",
                "Company_Name": "Otis",
                "Time_Period_Months": "12",
                "Designation": "Fitter",
                "RFL": "0",
                "Elec_Mech1": "Electrical",
                "Multiple_Sites": "yes",
            },
        ],
    )
    link(d, "rel#Candidate2#Major_Whereabout.csv", [("m1", "z2")])
    write(
        d,
        "basic#Mini_Whereabout.csv",
        [
            {
                "ID": "w1",
                "Added_Time": str(MS),
                "Added_User": "Z:usha.p@senkenindia.in",
                "Current_Company": "Kone",
                "Availability_Status": "No",
                "Notes": "not interested",
            },
        ],
    )
    link(d, "rel#Candidate#Mini_Whereabout.csv", [("w1", "z6")])
    # an interview on the card that does not lead its number
    write(
        d,
        "basic#Interviews.csv",
        [
            {
                "ID": "i1",
                "Added_Time": str(MS),
                "Date_field": "2026-08-12",
                "Name": "Person 1",
                "Phone_Number": "+919876543201",
                "Profile": "Elec + Mech",
                "Interview_Status": "Select",
                "Assessor": "Z:boavrishr@gmail.com",
                "Level_of_Candidate": "Expert",
                "HR_form_submitted": "true",
                "Preference": "Semi - preferred",
                "Offer_given_if_any": "18000",
                "Email": "a@b.co",
                "Temporary_Address": "Sector 4",
                "Expected_Salary_Monthly": "20000",
                "Joining_Period_Days": "7",
                "Total_Experience_Months": "24",
                "Wiring_Bunch": "true",
                "Roping": "true",
                "PFA_Assessor_Comments": "good",
            },
        ],
    )
    link(d, "rel#Candidate#Interviews.csv", [("i1", "z1")])
    write(
        d,
        "basic#Vehicle_Status@Interviews.csv",
        [
            {
                "ID": "v1",
                "Vehicle": "Bike",
                "Own": "true",
                "Driving_Status": "true",
                "DL_Status": "Yes",
            }
        ],
    )
    link(d, "rel#Vehicle_Status#Interviews.csv", [("i1", "v1")])
    write(
        d,
        "basic#Work_Experience@Interviews.csv",
        [
            {
                "ID": "w1",
                "Name_Of_Organization": "Otis",
                "Duration": "2 Years 1 Months",
                "Currently_Working": "false",
            }
        ],
    )
    link(d, "rel#Work_Experience#Interviews.csv", [("i1", "w1")])
    write(
        d,
        "basic#Educational_Background@Interviews.csv",
        [{"ID": "e1", "Academic_Qualification": "10th", "CGPA_Percentage_Grade": "77"}],
    )
    link(d, "rel#Educational_Background#Interviews.csv", [("i1", "e1")])
    return d


def run(export, apply=True):
    return legacy_import.run(export, export, apply=apply, log=lambda *a: None)


def test_dry_run_saves_nothing(export):
    stats, _ = run(export, apply=False)
    assert stats["cards"] == 6
    assert not Person.objects.exists() and not CallLog.objects.exists()


def test_cards_requisition_and_sourced_numbers(export):
    run(export)
    senken = Company.objects.get(slug="senken")
    assert Person.objects.filter(company=senken).count() == 6
    p = Person.objects.get(candidate_id="WJ3")
    assert (p.department, p.sub_department, p.source_reference) == (
        "operations",
        "Elec + Mech",
        "Indeed",
    )
    rows = SourcedNumber.objects.all()
    assert rows.count() == 6
    assert {r.requisition.profile for r in rows} == {"Data 13th Nov 26"}
    assert {r.source for r in rows} == {"Data 13th Nov 26"}
    # WJ1 and WJ2 share a number: WJ2 holds the calls and leads, WJ1 is archived
    assert Person.objects.get(candidate_id="WJ1").archived_at
    assert not Person.objects.get(candidate_id="WJ2").archived_at
    assert rows.get(person__candidate_id="WJ1").is_duplicate
    assert not rows.get(person__candidate_id="WJ2").is_duplicate


def test_second_number_goes_to_the_alternate_field(export):
    run(export)
    p = Person.objects.get(candidate_id="WJ1")
    assert (p.phone, p.alternate_phone) == ("9876543201", "9811100001")


def test_pinky_signs_as_the_existing_user_pratibha(django_user_model):
    pratibha = django_user_model.objects.create_user(
        username="S1", first_name="Pratibha", last_name="B"
    )
    assert legacy_import.Users().named("pratibha") == pratibha
    assert legacy_import.ALIASES["pinky"] == "pratibha"


def test_every_number_gets_its_own_field(export):
    run(export)
    p = Person.objects.get(candidate_id="WJ3")
    assert (p.phone, p.alternate_phone, p.phone_3, p.phone_4) == (
        "9876543203",
        "9811100009",
        "9811100003",
        "9811100004",
    )


def test_status_codes_become_status_and_the_date_goes(export):
    run(export)
    five = Person.objects.get(candidate_id="WJ5")
    assert five.contact_status == "on_demand"
    assert not FollowUp.objects.filter(person=five, status="pending").exists()
    six = Person.objects.get(candidate_id="WJ6")
    assert (six.contact_status, six.priority) == ("active", "semi")
    assert (six.department, six.sub_department) == ("bo", "Data Analyst")


def test_pending_calls_keep_their_owner_and_unassigned_go_to_nitin(
    export, django_user_model
):
    nishu = django_user_model.objects.create_user(username="S1", first_name="Nishu")
    run(export)
    three = FollowUp.objects.get(person__candidate_id="WJ3", status="pending")
    assert (
        three.owner == nishu
        and timezone.localtime(three.due).date().isoformat() == NEXT
    )
    four = FollowUp.objects.get(person__candidate_id="WJ4", status="pending")
    assert four.owner.first_name == "Nitin" and four.purpose == "interview"
    assert FollowUp.objects.filter(status="pending").count() == 2
    assert FollowUp.objects.filter(status="completed").count() == 1


def test_calls_signed_by_the_real_caller_and_shifts_are_left_out(export, monkeypatch):
    monkeypatch.setattr(legacy_import, "MIN_SIGNATURES", 2)
    stats, _ = run(export)
    assert (
        stats["call logs"] == 4
        and stats["call logs left out (shifts and parking)"] == 1
    )
    assert not CallLog.objects.filter(notes__contains="shift").exists()
    ringing = CallLog.objects.get(notes="ringing-taniya")
    assert ringing.caller.first_name == "Taniya" and not ringing.caller.is_active
    assert ringing.outcome == "reg_not_touch"
    # no signature: the login that made the call
    disc = CallLog.objects.get(notes="wants to talk")
    assert disc.caller.first_name == "Usha P" and disc.discussed
    # called when the call happened, not when it was imported
    assert CallLog.objects.get(notes="ringing - taniya").called_at.date() == date(
        2026, 8, 6
    )


def test_whereabouts_sit_on_their_call_or_make_one(export):
    run(export)
    major = CallLog.objects.get(notes="ringing-taniya").major_whereabout
    assert major["company_name"] == "Otis" and major["time_period_months"] == 12
    assert major["department"] == "elec_mech" and major["trade"] == "Electrical"
    assert "rfl" not in major  # "0" means not known
    mini = CallLog.objects.get(
        person__candidate_id="WJ6", notes__startswith="Whereabout"
    )
    assert mini.mini_whereabout["current_company"] == "Kone"


def test_interview_moves_to_the_main_card_and_updates_it(export):
    run(export)
    iv = Interview.objects.get()
    main = Person.objects.get(candidate_id="WJ2")
    assert iv.person == main  # WJ1 leads nothing: its interview follows the number
    assert iv.result == "selected" and iv.profile == "elec_mech"
    assert iv.answers["department"] == "operations" and iv.answers["trade"] == "Both"
    assert iv.answers["vehicles"][0]["vehicle"] == "Bike"
    assert iv.answers["work"][0]["duration"] == "25"
    assert iv.answers["education"][0]["qualification"] == "10th"
    assert iv.answers["elec_wiring_bunch"] == "Yes"
    hr = HRAssessment.objects.get()
    assert (hr.decision, hr.level, hr.answers["offer_given"]) == (
        "selected",
        "expert",
        18000,
    )
    main.refresh_from_db()
    assert (main.email, main.priority, main.expected_salary) == (
        "a@b.co",
        "semi",
        20000,
    )


def test_repeated_candidate_ids_stop_the_import(export):
    rows = list(
        csv.DictReader(
            open(export / "basic#Candidate_Master.csv", encoding="utf-8-sig")
        )
    )
    rows[1]["Candidate_ID"] = rows[0]["Candidate_ID"]
    write(export, "basic#Candidate_Master.csv", rows)
    with pytest.raises(RuntimeError, match="used twice"):
        run(export)
    assert not Person.objects.exists()


def test_the_earlier_of_two_dated_calls_is_kept_and_the_other_listed(export):
    rows = list(
        csv.DictReader(
            open(export / "basic#Candidate_Master.csv", encoding="utf-8-sig")
        )
    )
    # WJ3 and WJ4 share a number; WJ3 is dated later than WJ4
    rows[3]["Phone_No"] = rows[2]["Phone_No"]
    rows[2]["Next_Follow_Up_Date"] = (
        timezone.localdate() + timedelta(days=9)
    ).isoformat()
    write(export, "basic#Candidate_Master.csv", rows)
    _, review = run(export)
    assert [r[1] for r in review if r[0].startswith("second dated")] == ["WJ3"]
    # one call for the number, on its main card, at the earlier date
    (call,) = FollowUp.objects.filter(status="pending", person__phone="9876543203")
    assert timezone.localtime(call.due).date().isoformat() == NEXT


def test_cannot_run_twice(export):
    run(export)
    with pytest.raises(RuntimeError):
        run(export)


@pytest.mark.skipif(
    not os.environ.get("LEGACY_ARCHIVE"), reason="needs the real export"
)
def test_real_export_dry_run():
    """LEGACY_ARCHIVE=x.zip uv run pytest hiring/test_legacy_import.py -k real -s"""
    stats, review = legacy_import.from_archive(os.environ["LEGACY_ARCHIVE"], log=print)
    for k, v in stats.items():
        print(k, v if not k.startswith("_") else "")
    print(len(review), "review rows")
    from collections import Counter

    print(Counter(r[0] for r in review))
    print("matched", stats["_matched"])
    print("created", stats["_created"])
    print("shift", stats["_shift_notes"][:12])
    print("kept", stats["_other_notes"][:12])
    seen = Counter()
    for r in review:
        seen[r[0]] += 1
        if seen[r[0]] <= 2:
            print("EX", r)
