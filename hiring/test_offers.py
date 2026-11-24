from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.access import MODULES
from core.models import AccessGrant, Company

from .models import CallLog, FollowUp, HRAssessment, Offer, Requisition
from .services import (
    OfferError,
    accept,
    add_round,
    decline,
    log_call,
    offers_waiting,
    record_interview,
    source_number,
    start_offer,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def caller(client, django_user_model, senken):
    user = django_user_model.objects.create_user(username="S9", password="pw")
    senken.memberships.create(user=user)
    for tab in MODULES["recruitment"].sections:
        AccessGrant.objects.create(
            user=user, company=senken, module="recruitment", section=tab
        )
    client.force_login(user)
    return user


@pytest.fixture
def agent(django_user_model, caller):
    """The recruiter who sourced Asha; `caller` is their supervisor."""
    return django_user_model.objects.create_user(
        username="agent", password="pw", supervisor=caller
    )


TOMORROW = timezone.now() + timedelta(days=1)


@pytest.fixture
def waiting(senken, caller, agent):
    """Asha, selected at interview and waiting for a supervisor to make the offer."""
    req = Requisition.objects.create(
        company=senken, opened_by=caller, department="bo", profile="Fitter", headcount=2
    )
    source_number(req, "Asha", "9876543210", agent)
    FollowUp.objects.update(owner=agent)
    log_call(
        FollowUp.objects.get(),
        "reg_ff",
        agent,
        next_due=timezone.now() + timedelta(days=1),
        intention="interview",
    )
    return record_interview(FollowUp.objects.get(status="pending"), "selected", caller)


@pytest.fixture
def offer(waiting, caller):
    return start_offer(waiting, Decimal("30000"), caller, TOMORROW)


def test_make_offer_logs_round_one_and_drafts_the_call_for_the_supervisor(
    waiting, caller, agent
):
    assert waiting in offers_waiting(caller, [waiting.person.company])
    offer = start_offer(waiting, Decimal("30000"), caller, TOMORROW)
    assert (offer.state, offer.latest.amount) == ("offered", Decimal("30000"))
    call = FollowUp.objects.get(status="pending", purpose="offer")
    assert call.owner == caller and call.due.date() >= TOMORROW.date()
    assert waiting not in offers_waiting(caller, [waiting.person.company])
    # Later calls on the candidate stay with the supervisor.
    log_call(call, "reg_ff", agent, next_due=TOMORROW + timedelta(days=2))
    assert FollowUp.objects.get(status="pending").owner == caller


def test_only_a_supervisor_can_make_an_offer(client, waiting, agent):
    with pytest.raises(PermissionDenied):
        start_offer(waiting, Decimal("1"), agent, TOMORROW)
    client.force_login(agent)
    r = client.post(
        reverse("hiring:offer_start", args=[waiting.pk]),
        {"amount": "1", "follow_up": "2031-01-02"},
    )
    assert r.status_code == 403 and not Offer.objects.exists()


def test_hr_amount_and_date_prefill_the_form(client, waiting, caller):
    HRAssessment.objects.create(
        interview=waiting,
        assessor=caller,
        level="expert",
        decision="selected",
        answers={"offer_given": 21000, "next_follow_up": "2031-01-02"},
    )
    page = client.get(reverse("hiring:offer_start", args=[waiting.pk])).content
    assert b'value="21000' in page and b"2031-01-02" in page


def test_rounds_track_the_negotiation(offer, caller):
    add_round(
        offer, Decimal("32000"), caller, counter=Decimal("35000"), note="asked more"
    )
    assert offer.rounds.count() == 2
    assert offer.latest.counter == Decimal("35000")


def test_accept_books_the_joining(offer, caller):
    accept(offer, date(2030, 1, 6), caller)
    offer.refresh_from_db()
    assert (offer.state, offer.joining_date) == ("accepted", date(2030, 1, 6))
    joining = FollowUp.objects.get(purpose="joining")
    assert timezone.localtime(joining.due).date() == date(2030, 1, 6)


def test_a_closed_offer_cannot_change_again(offer, caller):
    decline(offer, "better offer elsewhere")
    for act in (
        lambda: add_round(offer, Decimal("1"), caller),
        lambda: accept(offer, date(2030, 1, 6), caller),
        lambda: decline(offer),
    ):
        with pytest.raises(OfferError):
            act()
    assert FollowUp.objects.filter(purpose="joining").count() == 0


def test_only_one_open_offer_per_person(offer, caller):
    with pytest.raises(IntegrityError):
        Offer.objects.create(person=offer.person, made_by=caller)


def test_pages_prefill_and_flow(client, waiting, caller):
    waiting.person.expected_salary = Decimal("28000")
    waiting.person.save()
    url = reverse("hiring:offer_start", args=[waiting.pk])
    assert b'value="28000' in client.get(url).content
    r = client.post(url, {"amount": "28000", "follow_up": "2031-01-02"})
    offer = Offer.objects.get()
    assert r.status_code == 302 and r.url == reverse("hiring:offer", args=[offer.pk])
    client.post(
        reverse("hiring:offer_round", args=[offer.pk]),
        {"amount": "30000", "counter": "33000"},
    )
    client.post(
        reverse("hiring:offer_accept", args=[offer.pk]), {"joining_date": "2030-01-06"}
    )
    offer.refresh_from_db()
    assert offer.state == "accepted" and offer.rounds.count() == 2
    assert b"Accepted" in client.get(reverse("hiring:offers")).content


def test_export(client, offer):
    book = load_workbook(BytesIO(client.get(reverse("hiring:offers_export")).content))
    assert list(book["Offers"].values)[1][3:5] == ("Offered", 30000.0)
    assert len(list(book["Rounds"].values)) == 2


# Joining can't be in the future, so the tests join on the day they accept.
JOINED = {
    "joined_on": timezone.localdate().isoformat(),
    "sim_allotted": "Yes",
    "resources": "Laptop, ID card",
    "notes": "On time",
}


def test_marking_joined_closes_the_joining_follow_up(client, offer, caller):
    accept(offer, date(2030, 1, 6), caller)
    r = client.post(reverse("hiring:joined", args=[offer.pk]), JOINED)
    assert r.status_code == 302
    offer.refresh_from_db()
    assert offer.joined_on == timezone.localdate()
    assert not FollowUp.objects.filter(purpose="joining", status="pending").exists()
    page = client.get(reverse("hiring:onboarding")).content.decode()
    assert f"joined {timezone.localdate():%d/%m/%Y}" in page and "coming soon" in page
    assert (offer.resources, offer.sim_allotted) == ("Laptop, ID card", "Yes")
    assert "SIM: Yes" in page and "Laptop, ID card" in page


def test_joining_needs_the_sim_answer(client, offer, caller):
    accept(offer, date(2030, 1, 6), caller)
    client.post(
        reverse("hiring:joined", args=[offer.pk]), {"joined_on": JOINED["joined_on"]}
    )
    offer.refresh_from_db()
    assert offer.joined_on is None


def test_only_accepted_unjoined_offers_can_join(client, offer, caller):
    client.post(reverse("hiring:joined", args=[offer.pk]), JOINED)
    offer.refresh_from_db()
    assert offer.joined_on is None
    accept(offer, date(2030, 1, 6), caller)
    for _ in range(2):
        client.post(reverse("hiring:joined", args=[offer.pk]), JOINED)
    offer.refresh_from_db()
    assert offer.joined_on == timezone.localdate()


def test_onboarding_export(client, offer, caller):
    accept(offer, date(2030, 1, 6), caller)
    book = load_workbook(
        BytesIO(client.get(reverse("hiring:onboarding_export")).content)
    )
    assert list(book["On-Boarding"].values)[1][0] == "Asha"


def test_joining_cannot_be_before_the_offer_was_accepted(client, offer, caller):
    accept(offer, date(2030, 1, 6), caller)
    client.post(
        reverse("hiring:joined", args=[offer.pk]), JOINED | {"joined_on": "2020-01-01"}
    )
    offer.refresh_from_db()
    assert offer.joined_on is None


def test_a_later_call_does_not_block_the_joining_date(client, offer, caller):
    accept(offer, date(2030, 1, 6), caller)
    CallLog.objects.create(person=offer.person, caller=caller, outcome="call")
    today = timezone.localdate().isoformat()
    client.post(
        reverse("hiring:joined", args=[offer.pk]), JOINED | {"joined_on": today}
    )
    offer.refresh_from_db()
    assert offer.joined_on == timezone.localdate()


def test_the_sim_choice_is_required_in_the_page_and_ids_do_not_repeat(
    client, offer, caller
):
    accept(offer, date(2030, 1, 6), caller)
    page = client.get(reverse("hiring:onboarding")).content.decode()
    assert page.count('name="sim_allotted"') == 2  # Yes and No
    assert page.count('name="sim_allotted" value="Yes" required') == 1
    assert 'id="id_sim_allotted' not in page


def test_offer_and_onboarding_exports_follow_the_filters(client, offer, caller):
    accept(offer, date(2030, 1, 6), caller)

    def rows(name, sheet, **get):
        book = load_workbook(
            BytesIO(client.get(reverse(f"hiring:{name}"), get).content)
        )
        return len(list(book[sheet].values)) - 1

    for name, sheet in (
        ("offers_export", "Offers"),
        ("onboarding_export", "On-Boarding"),
    ):
        assert rows(name, sheet) == 1
        assert rows(name, sheet, q="asha") == 1
        assert rows(name, sheet, q="zzz") == 0
        assert rows(name, sheet, requisition=offer.requisition_id) == 1
        assert rows(name, sheet, requisition=offer.requisition_id + 1) == 0


def test_a_stale_make_offer_cannot_offer_a_rejected_candidate(waiting, caller):
    from .models import Interview

    Interview.objects.create(
        person=waiting.person,
        scheduled_at=timezone.now(),
        result="rejected",
        interviewer=caller,
    )
    with pytest.raises(OfferError):
        start_offer(waiting, Decimal("1"), caller, TOMORROW)
