"""Edge cases found in the empanelment pipeline review: one test per fix."""

from datetime import date, timedelta
from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from core.models import AccessGrant, Company
from people.models import Person

from . import services as s
from .excel import SheetError, import_numbers
from .forms import BulkForm, JoinedForm, ReassignForm, RescheduleForm, ShiftForm
from .interview_form import AssessmentForm, InterviewForm
from .models import FollowUp, Interview, Requisition

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


def grant(user, company, *sections):
    company.memberships.get_or_create(user=user)
    for name in sections:
        AccessGrant.objects.create(
            user=user, company=company, module="recruitment", section=name
        )


@pytest.fixture
def user(django_user_model, senken):
    u = django_user_model.objects.create_user(username="u", password="pw")
    grant(u, senken)
    return u


@pytest.fixture
def req(senken, user):
    return Requisition.objects.create(
        company=senken, opened_by=user, department="bo", profile="F", headcount=2
    )


@pytest.fixture
def interview(req, user):
    """Asha, interviewed once and waiting for HR."""
    s.source_number(req, "Asha", "9876543210", user)
    s.log_call(
        FollowUp.objects.get(),
        "reg_ff",
        user,
        next_due=timezone.now(),
        intention="interview",
    )
    booked = FollowUp.objects.get(status="pending", purpose="interview")
    return s.record_interview(
        booked, "pending", user, answers={"email": "old@example.com"}
    )


def pending(person, purpose):
    return person.followups.filter(status="pending", purpose=purpose)


def sheet(rows):
    book = Workbook()
    book.active.append(["Name", "Phone"])
    for row in rows:
        book.active.append(row)
    out = BytesIO()
    book.save(out)
    out.seek(0)
    out.size = len(out.getvalue())
    return out


# 1 -------------------------------------------------------------------------
def test_saving_hr_again_does_not_reopen_an_offer_already_made(interview, user):
    s.save_assessment(interview, "selected", "expert", user, answers={"offer_given": 9})
    s.start_offer(pending(interview.person, "offer").get(), 9, user)
    s.save_assessment(
        interview, "selected", "expert", user, comments="x", answers={"offer_given": 9}
    )
    assert not pending(interview.person, "offer").exists()
    assert interview.person.offers.count() == 1


# 2 -------------------------------------------------------------------------
def test_hr_save_does_not_overwrite_newer_card_edits_but_keeps_preference(
    interview, user
):
    person = interview.person
    person.email, person.version = "new@example.com", person.version + 1
    person.save()
    s.save_assessment(
        interview, "selected", "expert", user, answers={"preference": "preferred"}
    )
    person.refresh_from_db()
    assert (person.email, person.priority) == ("new@example.com", "preferred")


# 3 -------------------------------------------------------------------------
def test_hold_needs_a_follow_up_date():
    form = AssessmentForm({"decision": "hold"})
    assert not form.is_valid() and "next_follow_up" in form.errors
    ok = AssessmentForm({"decision": "hold", "next_follow_up": "2031-05-01"})
    assert ok.is_valid()
    assert AssessmentForm({"decision": "rejected"}).is_valid()


# 4 -------------------------------------------------------------------------
def test_a_bad_time_of_birth_is_refused_and_never_crashes(interview):
    form = InterviewForm({"time_of_birth": "25:00"})
    form.is_valid()
    assert "time_of_birth" in form.errors
    interview.answers = {"time_of_birth": "25:00"}  # already saved before the fix
    s.apply_to_person(interview)  # must not raise


# 5 -------------------------------------------------------------------------
def test_import_skips_cells_the_columns_cannot_hold(req, user):
    new, dups, skipped = import_numbers(
        req, sheet([["x" * 300, "9123456789"], ["Ok", "9123456780"]]), user
    )
    assert (new, dups) == (1, 0)
    assert skipped[0][0] == 2 and "longer than 200" in skipped[0][1]


def test_import_ignores_formatted_empty_rows_below_the_data(req, user):
    rows = [["Ok", "9123456780"]] + [[None, None]] * 3000
    assert import_numbers(req, sheet(rows), user)[:2] == (1, 0)


def test_import_over_the_row_limit_is_refused_not_trimmed(req, user):
    rows = [[f"P{i}", f"9{i:09d}"] for i in range(2001)]
    with pytest.raises(SheetError):
        import_numbers(req, sheet(rows), user)
    assert not Person.objects.exists()


# 6 -------------------------------------------------------------------------
@pytest.mark.parametrize("status", ["do_not_call", "closed"])
def test_a_card_that_must_not_be_called_gets_no_call(senken, req, user, status):
    Person.objects.create(
        company=senken, name="D", phone="9000000001", contact_status=status
    )
    made = s.source_number(req, "D", "9000000001", user)
    assert made.is_duplicate and not FollowUp.objects.exists()


def test_a_candidate_with_an_accepted_offer_gets_no_call(interview, req, user):
    s.save_assessment(interview, "selected", "expert", user, answers={"offer_given": 9})
    offer = s.start_offer(pending(interview.person, "offer").get(), 9, user)
    s.accept(offer, date(2031, 6, 1), user)
    s.mark_joined(offer, date(2031, 6, 1))
    s.source_number(req, "Asha", "9876543210", user)
    assert not pending(interview.person, "call").exists()


# 7 -------------------------------------------------------------------------
def test_hr_panel_and_export_follow_the_interviews_own_company(
    client, django_user_model, senken, interview, user
):
    other = Company.objects.create(name="Other Co", slug="other")
    s.save_assessment(interview, "selected", "expert", user, comments="secret")
    url = reverse("hiring:interview_review", args=[interview.pk])

    def hr_text():
        out = client.get(reverse("hiring:selecting_export"))
        book = load_workbook(BytesIO(out.content))
        return "|".join(
            str(c.value)
            for name in book.sheetnames
            for r in book[name].iter_rows()
            for c in r
            if name == "HR assessments"
        )

    wrong = django_user_model.objects.create_user(username="v", password="pw")
    grant(wrong, senken, "selecting", "hiring")
    grant(wrong, other, "assessments", "hiring")  # HR only in the other company
    client.force_login(wrong)
    assert client.get(url).context["hr_form"] is None
    assert "secret" not in hr_text()

    right = django_user_model.objects.create_user(username="r2", password="pw")
    grant(right, senken, "selecting", "hiring", "assessments")
    client.force_login(right)
    assert client.get(url).context["hr_form"] is not None
    assert "secret" in hr_text()  # the control: the right grant does see it


# 8 -------------------------------------------------------------------------
def test_hiring_access_reads_an_interview_but_cannot_change_it(
    client, django_user_model, senken, interview
):
    reader = django_user_model.objects.create_user(username="r", password="pw")
    grant(reader, senken, "hiring")
    client.force_login(reader)
    url = reverse("hiring:interview_review", args=[interview.pk])
    assert client.get(url).status_code == 200
    assert client.post(url, {"profile": "bo"}).status_code == 403


def test_hiring_page_lists_only_interviews_you_can_open(
    client, django_user_model, senken, interview
):
    from core.models import Company

    other = Company.objects.create(name="Other Co")
    reader = django_user_model.objects.create_user(username="r2", password="pw")
    grant(reader, senken, "selecting")  # a member of Senken, but not for Hiring
    grant(reader, other, "hiring")
    client.force_login(reader)
    page = client.get(reverse("hiring:offers")).content
    assert b"Asha" not in page
    url = reverse("hiring:interview_review", args=[interview.pk])
    assert client.get(url).status_code == 404


def test_joining_days_reads_ranges_weeks_and_months():
    from hiring.selecting_views import joining_days

    cases = {"15 days": 15, "15-20 days": 15, "2 weeks": 14, "1 month": 30}
    assert {k: joining_days(k) for k in cases} == cases
    assert joining_days("immediately") == "" and joining_days("") == ""


def test_editing_an_interview_keeps_a_later_card_correction(interview, user):
    person = interview.person
    s.edit_interview(interview, "pending", "", "", answers={"email": "old@example.com"})
    person.refresh_from_db()
    person.email = "fixed@example.com"
    person.save()
    s.edit_interview(
        interview,
        "pending",
        "",
        "x",
        answers={"email": "old@example.com", "place_of_birth": "Pune"},
    )
    person.refresh_from_db()
    assert person.email == "fixed@example.com" and person.place_of_birth == "Pune"


def test_review_needs_the_hr_grant_to_post_the_hr_form(
    client, django_user_model, senken, interview
):
    reader = django_user_model.objects.create_user(username="r3", password="pw")
    grant(reader, senken, "hiring")
    client.force_login(reader)
    url = reverse("hiring:interview_review", args=[interview.pk])
    assert client.post(url, {"which": "hr"}).status_code == 403


def test_a_bad_upload_is_refused_and_a_good_one_replaces_the_old(
    rf, interview, settings, tmp_path
):
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.core.files.uploadedfile import SimpleUploadedFile

    from hiring.selecting_views import _files

    settings.MEDIA_ROOT = tmp_path

    def send(**files):
        request = rf.post("/", files)
        request.session = {}
        request._messages = FallbackStorage(request)
        _files(request, interview)

    send(photo=SimpleUploadedFile("a.txt", b"hi", content_type="text/plain"))
    assert not interview.photo
    send(photo=SimpleUploadedFile("a.png", b"x", content_type="image/png"))
    first = interview.photo.name
    send(photo=SimpleUploadedFile("b.png", b"y", content_type="image/png"))
    assert interview.photo.name != first and not (tmp_path / first).exists()


# 9 + 11 --------------------------------------------------------------------
def test_a_declined_candidate_interviewed_again_gets_an_offer_task(interview, user):
    s.save_assessment(interview, "selected", "expert", user)
    s.decline(s.start_offer(pending(interview.person, "offer").get(), 9, user))
    again = Interview.objects.create(
        person=interview.person,
        scheduled_at=timezone.now(),
        result="pending",
        interviewer=user,
    )
    s.edit_interview(again, "selected", "", "")
    assert pending(interview.person, "offer").count() == 1


def test_saving_the_same_interview_again_after_a_decline_opens_nothing(interview, user):
    s.save_assessment(interview, "selected", "expert", user)
    s.decline(s.start_offer(pending(interview.person, "offer").get(), 9, user))
    s.edit_interview(interview, "selected", "new notes", "", answers={"email": "a@b.c"})
    s.save_assessment(interview, "selected", "expert", user, answers={"offer_given": 9})
    assert not pending(interview.person, "offer").exists()


def test_rejecting_cancels_the_offer_task_and_an_amount_alone_is_no_offer(
    interview, user
):
    s.save_assessment(interview, "selected", "expert", user)
    assert pending(interview.person, "offer").count() == 1
    s.save_assessment(interview, "rejected", "", user, answers={"offer_given": 500})
    assert not pending(interview.person, "offer").exists()


# 10 ------------------------------------------------------------------------
def test_stage_after_a_decline_follows_the_newer_interview(interview, user):
    s.save_assessment(interview, "selected", "expert", user)
    s.decline(s.start_offer(pending(interview.person, "offer").get(), 9, user))
    assert s.stage(interview.person) == "Offer declined"
    Interview.objects.create(
        person=interview.person,
        scheduled_at=timezone.now(),
        result="rejected",
        interviewer=user,
    )
    assert s.stage(interview.person) == "Not selected"


# 12 ------------------------------------------------------------------------
def test_a_second_offer_task_cannot_start_a_second_open_offer(interview, user):
    s.save_assessment(interview, "selected", "expert", user)
    s.start_offer(pending(interview.person, "offer").get(), 9, user)
    extra = FollowUp.objects.create(
        person=interview.person, purpose="offer", due=timezone.now(), owner=user
    )
    with pytest.raises(s.OfferError):
        s.start_offer(extra, 9, user)


def test_an_accepted_candidate_cannot_be_offered_again(interview, user):
    s.save_assessment(interview, "selected", "expert", user)
    offer = s.start_offer(pending(interview.person, "offer").get(), 9, user)
    s.accept(offer, date(2031, 6, 1), user)
    extra = FollowUp.objects.create(
        person=interview.person, purpose="offer", due=timezone.now(), owner=user
    )
    with pytest.raises(s.OfferError):
        s.start_offer(extra, 9, user)


def test_hr_offer_with_a_newer_call_waiting_uses_the_offer_task(interview, user):
    s.save_assessment(interview, "selected", "expert", user)
    s.schedule_call(interview.person, timezone.now() + timedelta(days=1), user)
    s.save_assessment(interview, "selected", "expert", user, answers={"offer_given": 9})
    assert pending(interview.person, "offer").count() == 1
    assert pending(interview.person, "call").count() == 1


# 13 ------------------------------------------------------------------------
def test_bulk_move_leaves_interviews_and_joinings_alone(interview, user):
    FollowUp.objects.create(
        person=interview.person, purpose="update", due=timezone.now(), owner=user
    )
    booked = FollowUp.objects.create(
        person=interview.person, purpose="interview", due=timezone.now(), owner=user
    )
    due = booked.due
    s.bulk_move(FollowUp.objects.filter(status="pending"), date(2031, 5, 1), "holiday")
    booked.refresh_from_db()
    assert booked.due == due


# 14 ------------------------------------------------------------------------
def test_sourcing_for_another_requisition_moves_a_waiting_call_to_it(senken, req, user):
    s.source_number(req, "Asha", "9876543210", user)
    second = Requisition.objects.create(
        company=senken, opened_by=user, department="bo", profile="G", headcount=1
    )
    s.source_number(second, "Asha", "9876543210", user)
    assert FollowUp.objects.get().requisition == second


# 15 ------------------------------------------------------------------------
def test_reassign_offers_only_people_who_can_open_the_queue(
    django_user_model, senken, user
):
    worker = django_user_model.objects.create_user(username="w", password="pw")
    grant(worker, senken, "calling")
    outsider = django_user_model.objects.create_user(username="o", password="pw")
    grant(outsider, senken)
    owners = ReassignForm(companies=[senken]).fields["owner"].queryset
    hirer = django_user_model.objects.create_user(username="h", password="pw")
    grant(hirer, senken, "hiring")
    owners = ReassignForm(companies=[senken]).fields["owner"].queryset
    assert {worker, hirer} <= set(owners) and outsider not in owners


# 16 ------------------------------------------------------------------------
def test_a_call_refused_for_no_supervisor_keeps_what_was_typed(
    client, django_user_model, senken, req, user
):
    boss_less = django_user_model.objects.create_user(username="c", password="pw")
    grant(boss_less, senken, "screening", "calling")
    s.source_number(req, "Asha", "9876543210", boss_less)
    todo = FollowUp.objects.get()
    client.force_login(boss_less)
    out = client.post(
        reverse("hiring:followup_call", args=[todo.pk]),
        {
            "outcome": "reg_touch",
            "call_type": "outbound",
            "intention": "call",
            "next_due": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "notes": "long careful notes",
            "discuss": "on",
        },
    )
    assert out.status_code == 200 and "long careful notes" in out.content.decode()
    todo.refresh_from_db()
    assert todo.status == "pending"


# 17 ------------------------------------------------------------------------
def test_sourcing_holds_a_lock_on_the_number_and_a_repeat_finds_the_card(req, user):
    from django.db import connection

    s.source_number(req, "Asha", "9876543210", user)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_locks "
            "WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
        )
        assert cursor.fetchone()[0] == 1
    s.source_number(req, "Asha again", "+91 98765 43210", user)
    assert Person.objects.count() == 1


# 18 ------------------------------------------------------------------------
def test_did_not_join_ends_the_offer_and_cancels_the_joining_task(interview, user):
    s.save_assessment(interview, "selected", "expert", user)
    offer = s.start_offer(pending(interview.person, "offer").get(), 9, user)
    s.accept(offer, date(2031, 6, 1), user)
    s.did_not_join(offer, "took another job")
    offer.refresh_from_db()
    assert (offer.state, offer.decline_reason) == (
        "declined",
        "Did not join. took another job",
    )
    assert not pending(interview.person, "joining").exists()
    with pytest.raises(s.OfferError):
        s.did_not_join(offer)


def test_mark_joined_keeps_history_on_the_joining_task(interview, user):
    s.save_assessment(interview, "selected", "expert", user)
    offer = s.start_offer(pending(interview.person, "offer").get(), 9, user)
    s.accept(offer, date(2031, 6, 1), user)
    s.mark_joined(offer, date(2031, 6, 1))
    joining = interview.person.followups.get(purpose="joining")
    assert joining.status == "completed" and joining.history.count() == 2


# 19 ------------------------------------------------------------------------
def test_timeline_names_the_owner_at_the_time(django_user_model, interview, user):
    a = django_user_model.objects.create_user(username="a", password="pw")
    b = django_user_model.objects.create_user(username="b", password="pw")
    todo = FollowUp.objects.create(
        person=interview.person, purpose="update", due=timezone.now(), owner=user
    )
    for owner in (a, b):
        todo.owner = owner
        todo.save()
    texts = [e[2] for e in s.timeline(interview.person)]
    assert "Update given to A" in texts and "Update given to B" in texts


# 20 + 21 -------------------------------------------------------------------
def test_past_days_are_refused_for_moves_and_joining():
    yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
    assert not RescheduleForm({"due": yesterday, "reason": "holiday"}).is_valid()
    shift = {"group": "all", "day": yesterday, "reason": "holiday"}
    assert not ShiftForm(shift).is_valid()
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    assert (
        JoinedForm({"joined_on": tomorrow, "sim_allotted": "Yes"}).is_valid() is False
    )
    bulk = {"scope": "all", "do": "move", "day": yesterday, "reason": "holiday"}
    assert not BulkForm(bulk, companies=Company.objects.all()).is_valid()


# 22 ------------------------------------------------------------------------
def test_experience_and_money_answers_have_a_ceiling():
    form = InterviewForm({"experience_months": "100000", "expected_salary": "1"})
    form.is_valid()
    assert "experience_months" in form.errors


# 23 ------------------------------------------------------------------------
def test_requisition_timeline_counts_each_day_once(req, user):
    for i in range(3):
        s.source_number(req, f"P{i}", f"900000000{i}", user)
    texts = [e[2] for e in s.requisition_timeline(req)]
    assert "3 numbers received" in texts


# review follow-ups ----------------------------------------------------------
def test_bulk_move_says_when_it_left_interviews_alone(
    client, django_user_model, senken, interview, user
):
    boss = django_user_model.objects.create_superuser(username="boss", password="pw")
    grant(boss, senken)
    client.force_login(boss)
    booked = FollowUp.objects.create(
        person=interview.person, purpose="interview", due=timezone.now(), owner=user
    )
    out = client.post(
        reverse("hiring:bulk"),
        {
            "scope": "ticked",
            "do": "move",
            "ids": [booked.pk],
            "day": (timezone.localdate() + timedelta(days=2)).isoformat(),
            "reason": "holiday",
            "filters": "",
        },
        follow=True,
    )
    assert "No calls to move" in out.content.decode()


def test_a_malformed_hold_date_gets_one_error_not_two():
    form = AssessmentForm({"decision": "hold", "next_follow_up": "2031-02-30"})
    form.is_valid()
    assert len(form.errors["next_follow_up"]) == 1


def test_a_hold_date_in_the_past_is_refused():
    yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
    today = timezone.localdate().isoformat()
    past = AssessmentForm({"decision": "hold", "next_follow_up": yesterday})
    assert not past.is_valid() and "before today" in past.errors["next_follow_up"][0]
    assert AssessmentForm({"decision": "hold", "next_follow_up": today}).is_valid()
    # Other decisions keep their date as typed.
    assert AssessmentForm(
        {"decision": "selected", "next_follow_up": yesterday}
    ).is_valid()
