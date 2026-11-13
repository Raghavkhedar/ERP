from datetime import timedelta
from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.models import AccessGrant, Company

from .models import FollowUp, HRAssessment, Interview, Requisition
from .services import FollowUpError, log_call, record_interview, source_number

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


def member(django_user_model, senken, name, *sections):
    user = django_user_model.objects.create_user(username=name, password="pw")
    senken.memberships.create(user=user)
    for section in sections:
        AccessGrant.objects.create(
            user=user, company=senken, module="recruitment", section=section
        )
    return user


@pytest.fixture
def caller(client, django_user_model, senken):
    user = member(django_user_model, senken, "S9", "selecting")
    client.force_login(user)
    return user


@pytest.fixture
def booked(senken, caller):
    req = Requisition.objects.create(
        company=senken, opened_by=caller, department="bo", profile="Fitter", headcount=2
    )
    source_number(req, "Asha", "9876543210", caller)
    log_call(
        FollowUp.objects.get(),
        "reg_ff",
        caller,
        next_due=timezone.now() + timedelta(days=1),
        intention="interview",
    )
    return FollowUp.objects.get(status="pending", purpose="interview")


def test_selected_records_the_interview_and_opens_an_offer(booked, caller):
    record_interview(booked, "selected", caller, questions="PLC?")
    interview = Interview.objects.get()
    assert (interview.result, interview.scheduled_at) == ("selected", booked.due)
    assert interview.requisition == booked.requisition
    assert FollowUp.objects.filter(status="pending", purpose="offer").count() == 1


def test_hold_needs_a_date_to_open_a_call_and_rejected_opens_nothing(booked, caller):
    record_interview(booked, "hold", caller)
    assert not FollowUp.objects.filter(status="pending").exists()


def test_hold_with_a_date_opens_a_call(booked, caller):
    record_interview(booked, "hold", caller, next_due=timezone.now())
    assert FollowUp.objects.get(status="pending").purpose == "call"


def test_an_interview_cannot_be_recorded_twice(booked, caller):
    record_interview(booked, "rejected", caller)
    with pytest.raises(FollowUpError):
        record_interview(booked, "selected", caller)
    assert Interview.objects.count() == 1


FORM = {
    "profile": "bo",
    "date": "2031-01-05",
    "place_of_assessment": "Pune",
    "temporary_address": "Flat 2, Baner",
    "permanent_address": "Village X",
    "highest_education": "ITI",
    "experience_months": "30",
    "departments_worked_in": "Fitting",
    "last_ctc": "18000",
    "expected_salary": "22000",
    "family": "Four members",
    "away_from_family": "Lives with a cousin",
    "joining_days": "15",
    "place_of_birth": "Nashik",
    "date_of_birth": "1998-02-03",
    "time_of_birth": "06:30",
    "vehicle_status": "No vehicle",
    "assessor": 1,
    "edu_qualification": ["ITI", ""],
    "work_organization": ["ABC Works"],
    "edu_year": ["2016", ""],
}


def test_record_through_the_page(client, booked, caller, django_user_model):
    boss = django_user_model.objects.create_superuser("boss", password="pw")
    r = client.post(
        reverse("hiring:interview", args=[booked.pk]), {**FORM, "assessor": caller.pk}
    )
    assert r.status_code == 302
    interview = Interview.objects.get()
    assert interview.result == "pending" and interview.profile == "bo"
    edu = interview.answers["education"]
    assert (
        len(edu) == 1 and edu[0]["qualification"] == "ITI" and edu[0]["year"] == "2016"
    )
    assert interview.answers["vehicles"] == []
    assert interview.answers["work"][0]["organization"] == "ABC Works"
    person = interview.person
    person.refresh_from_db()
    assert (person.experience_years, person.highest_education) == (2.5, "ITI")
    assert str(person.date_of_birth) == "1998-02-03" and person.address.startswith(
        "Flat"
    )
    assert boss.notifications.filter(text__contains="Asha").exists()
    # an offer waits for HR's decision, not for the interviewer's form
    assert not FollowUp.objects.filter(status="pending", purpose="offer").exists()


def test_the_form_needs_the_asterisked_answers(client, booked):
    r = client.post(reverse("hiring:interview", args=[booked.pk]), {"profile": "bo"})
    assert r.status_code == 200 and not Interview.objects.exists()


def test_review_and_hr_form_only_for_the_right_people(
    client, booked, caller, django_user_model, senken
):
    client.post(
        reverse("hiring:interview", args=[booked.pk]), {**FORM, "assessor": caller.pk}
    )
    pk = Interview.objects.get().pk
    url = reverse("hiring:interview_review", args=[pk])
    assert client.get(url).status_code == 403  # selecting only
    desk = member(django_user_model, senken, "S4", "hiring")
    client.force_login(desk)
    page = client.get(url)
    assert page.status_code == 200 and b"HR assessment" not in page.content
    client.post(url, {"which": "hr", "decision": "selected"})
    assert not HRAssessment.objects.exists()
    boss = django_user_model.objects.create_superuser("boss", password="pw")
    client.force_login(boss)
    assert b"HR assessment (PFA)" in client.get(url).content
    r = client.post(
        url,
        {
            "which": "hr",
            "decision": "selected",
            "level": "expert",
            "preference": "preferred",
        },
    )
    assert r.status_code == 302
    hr = HRAssessment.objects.get()
    assert hr.level == "expert"
    interview = Interview.objects.get()
    assert interview.result == "selected"
    assert interview.person.priority == "preferred"
    assert FollowUp.objects.filter(status="pending", purpose="offer").exists()


def test_review_edit_updates_the_answers_and_the_card(
    client, booked, caller, django_user_model
):
    client.post(
        reverse("hiring:interview", args=[booked.pk]), {**FORM, "assessor": caller.pk}
    )
    interview = Interview.objects.get()
    boss = django_user_model.objects.create_superuser("boss", password="pw")
    client.force_login(boss)
    client.post(
        reverse("hiring:interview_review", args=[interview.pk]),
        {
            **FORM,
            "assessor": caller.pk,
            "which": "interview",
            "expected_salary": "25000",
        },
    )
    interview.refresh_from_db()
    assert interview.answers["expected_salary"] == 25000
    assert interview.person.expected_salary == 25000


def test_export_hides_hr_from_non_hr(client, booked, caller):
    record_interview(booked, "selected", caller)
    book = load_workbook(
        BytesIO(client.get(reverse("hiring:selecting_export")).content)
    )
    assert book.sheetnames == ["Interviews"]


def test_photo_and_resume_are_kept_and_served_only_to_the_hiring_tab(
    client, booked, caller, django_user_model, settings, tmp_path
):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = tmp_path
    client.post(
        reverse("hiring:interview", args=[booked.pk]),
        {
            **FORM,
            "assessor": caller.pk,
            "resume": SimpleUploadedFile("cv.pdf", b"%PDF-1"),
        },
    )
    interview = Interview.objects.get()
    assert interview.resume and not interview.photo
    url = reverse("hiring:interview_file", args=[interview.pk, "resume"])
    assert client.get(url).status_code == 403  # selecting only
    boss = django_user_model.objects.create_superuser("boss", password="pw")
    client.force_login(boss)
    assert client.get(url).status_code == 200
    assert (
        client.get(
            reverse("hiring:interview_file", args=[interview.pk, "photo"])
        ).status_code
        == 404
    )


def test_a_profile_brings_its_own_questions_and_tables(client, booked, caller):
    data = {
        **FORM,
        "assessor": caller.pk,
        "profile": "apprentice",
        "apprentice-internship": "6 months",
        "proj_name": ["Robot arm"],
    }
    client.post(reverse("hiring:interview", args=[booked.pk]), data)
    answers = Interview.objects.get().answers
    assert answers["internship"] == "6 months"
    assert answers["projects"][0]["name"] == "Robot arm"
    assert answers["work"] == []  # BO's table is not this profile's


def test_work_months_edge_cases():
    from datetime import date

    from .interview_form import work_months

    today = date(2031, 6, 15)
    assert work_months("2030-01-10", "2030-07-09", "No", today) == 5  # day not reached
    assert work_months("2030-01-10", "2030-07-10", "No", today) == 6
    assert work_months("2030-06-15", "", "Yes", today) == 12  # still there: to today
    assert work_months("2030-01-01", "", "No", today) is None  # no end, not current
    assert work_months("2030-05-01", "2030-01-01", "No", today) is None  # backwards
    assert work_months("2032-01-01", "", "Yes", today) is None  # not begun


def test_still_working_drops_the_end_date_and_sets_the_months(client, booked, caller):
    data = {
        **FORM,
        "assessor": caller.pk,
        "work_start": ["2020-01-01", "2019-01-01"],
        "work_current": ["Yes", "No"],
        "work_end": ["2020-06-01", "2019-03-15"],
        "work_duration": ["99", "99"],
        "work_organization": ["Now Ltd", "Then Ltd"],
    }
    client.post(reverse("hiring:interview", args=[booked.pk]), data)
    now, then = Interview.objects.get().answers["work"]
    assert now["end"] == "" and int(now["duration"]) > 60
    assert then["duration"] == "2"  # typed 99 is ignored: the dates decide


def test_the_form_pages_render(client, booked, caller, django_user_model):
    page = client.get(reverse("hiring:interview", args=[booked.pk]))
    assert page.status_code == 200 and b"Where they live" in page.content
    client.post(
        reverse("hiring:interview", args=[booked.pk]), {**FORM, "assessor": caller.pk}
    )
    boss = django_user_model.objects.create_superuser("boss", password="pw")
    client.force_login(boss)
    url = reverse("hiring:interview_review", args=[Interview.objects.get().pk])
    page = client.get(url)
    assert page.status_code == 200 and b"Still working here" in page.content


def test_vehicle_rows_are_kept_only_for_someone_with_a_vehicle(client, booked, caller):
    rows = {"veh_vehicle": ["Bike"], "veh_own": ["Yes"]}
    url = reverse("hiring:interview", args=[booked.pk])
    client.post(url, {**FORM, "assessor": caller.pk, **rows})
    assert Interview.objects.get().answers["vehicles"] == []
    Interview.objects.all().delete()
    booked.refresh_from_db()
    FollowUp.objects.filter(pk=booked.pk).update(status="pending")
    client.post(
        url, {**FORM, "assessor": caller.pk, "vehicle_status": "Has a vehicle", **rows}
    )
    assert Interview.objects.get().answers["vehicles"][0]["vehicle"] == "Bike"


def test_elec_mech_asks_only_the_chosen_departments_work(client, booked, caller):
    data = {
        **FORM,
        "assessor": caller.pk,
        "profile": "elec_mech",
        "elec_mech-trade": "Electrical",
    }
    url = reverse("hiring:interview", args=[booked.pk])
    assert b"Wiring bunch" in client.get(url).content
    client.post(
        url,
        {**data, "elec_mech-elec_wiring_bunch": "Yes", "elec_mech-mech_roping": "No"},
    )
    answers = Interview.objects.get().answers
    assert answers["elec_wiring_bunch"] == "Yes"
    assert "mech_roping" not in answers  # Mechanical list wasn't picked


def test_elec_mech_both_keeps_both_lists(client, booked, caller):
    data = {
        **FORM,
        "assessor": caller.pk,
        "profile": "elec_mech",
        "elec_mech-trade": "Both",
        "elec_mech-elec_wiring_bunch": "Yes",
        "elec_mech-mech_roping": "No",
    }
    client.post(reverse("hiring:interview", args=[booked.pk]), data)
    answers = Interview.objects.get().answers
    assert answers["elec_wiring_bunch"] == "Yes" and answers["mech_roping"] == "No"
