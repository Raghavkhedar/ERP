from datetime import timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from core.models import AccessGrant, Company
from people.models import Person

from .models import FollowUp, Requisition, SourcedNumber
from .services import source_number

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def caller(client, django_user_model, senken):
    user = django_user_model.objects.create_user(username="S9", password="pw")
    senken.memberships.create(user=user)
    for name in ("sourcing", "people", "openings"):
        AccessGrant.objects.create(
            user=user, company=senken, module="recruitment", section=name
        )
    client.force_login(user)
    return user


@pytest.fixture
def req(senken, caller):
    return Requisition.objects.create(
        company=senken, opened_by=caller, department="bo", profile="Fitter", headcount=3
    )


def sheet(*rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    out = BytesIO()
    book.save(out)
    return SimpleUploadedFile("n.xlsx", out.getvalue())


def test_new_number_makes_a_card_and_repeat_links_to_it(req, caller):
    a = source_number(req, "Asha", "+91 98765 43210", caller, "Naukri")
    b = source_number(req, "Asha K", "09876543210", caller, "Referral")
    assert (a.is_duplicate, b.is_duplicate) == (False, True)
    assert b.person == a.person and Person.objects.count() == 1
    assert SourcedNumber.objects.count() == 2


def test_short_number_rejected(req, caller):
    with pytest.raises(ValueError):
        source_number(req, "X", "12345", caller)
    assert not SourcedNumber.objects.exists()


def test_add_form_and_counts_on_requisition_list(client, req):
    for phone in ("9876543210", "9876543210", "9123456789"):
        r = client.post(
            reverse("hiring:source_new"),
            {"requisition": req.pk, "name": "A", "phone": phone, "source": "Naukri"},
        )
        assert r.status_code == 302
    assert Person.objects.count() == 2
    page = client.get(reverse("hiring:list")).content.decode()
    assert "3 sourced of 3 needed" in page and "1 duplicate" in page


def test_add_form_saves_experience_and_expected_salary(client, req):
    client.post(
        reverse("hiring:source_new"),
        {
            "requisition": req.pk,
            "name": "A",
            "phone": "9876543210",
            "experience_months": "18",
            "expected_salary": "25000",
        },
    )
    p = Person.objects.get()
    assert (p.experience_years, p.expected_salary) == (1.5, 25000)


def test_closed_requisition_cannot_be_sourced(client, req):
    req.status = "closed"
    req.save()
    r = client.post(
        reverse("hiring:source_new"),
        {"requisition": req.pk, "name": "A", "phone": "9876543210"},
    )
    assert r.status_code == 200 and not SourcedNumber.objects.exists()


def test_import_counts_new_duplicates_and_skips(client, req):
    upload = sheet(
        ("Name", "Mobile", "Source"),
        ("Asha", 9876543210.0, "Naukri"),
        ("Asha again", "+91 98765 43210", None),
        ("Bad", "123", None),
        (None, "9123456789", None),
        ("Ravi", "9123456780", None),
    )
    r = client.post(
        reverse("hiring:source_import"),
        {"requisition": req.pk, "source": "Walk-in", "sheet": upload},
        follow=True,
    )
    assert "2 new, 1 duplicate. Skipped 2" in r.content.decode()
    assert list(
        SourcedNumber.objects.order_by("id").values_list("source", flat=True)
    ) == ["Naukri", "Walk-in", "Walk-in"]


def test_import_without_headings_is_refused(client, req):
    r = client.post(
        reverse("hiring:source_import"),
        {"requisition": req.pk, "sheet": sheet(("Asha", "9876543210"))},
    )
    assert b"Name and Phone headings" in r.content
    assert not SourcedNumber.objects.exists()


def test_filter_and_export(client, req, caller):
    source_number(req, "A", "9876543210", caller, "Naukri")
    source_number(req, "A", "9876543210", caller, "Naukri")
    page = client.get(reverse("hiring:sourcing") + "?dup=1").content.decode()
    assert page.count(">Duplicate<") == 1
    r = client.get(reverse("hiring:sourcing_export"))
    book = load_workbook(BytesIO(r.content))
    assert list(book["By source"].values)[1] == ("Naukri", 2, 1, 0.5)


def test_other_company_is_hidden(client, req, caller):
    other = Company.objects.exclude(slug="senken").first()
    foreign = Requisition.objects.create(
        company=other, opened_by=caller, department="bo", profile="Zed", headcount=1
    )
    source_number(foreign, "Hidden", "9876543210", caller)
    assert b"Hidden" not in client.get(reverse("hiring:sourcing")).content


def test_source_is_a_listed_portal_or_other_with_a_name(client, req):
    url = reverse("hiring:source_new")
    row = {"requisition": req.pk, "name": "A", "phone": "9876543210"}
    assert client.post(url, row | {"source": "Facebook"}).status_code == 200
    assert client.post(url, row | {"source": "other"}).status_code == 200  # no name
    assert not SourcedNumber.objects.exists()
    r = client.post(url, row | {"source": "other", "source_other": "Walk-in"})
    assert r.status_code == 302
    assert SourcedNumber.objects.get().source == "Walk-in"


def test_save_and_add_another_keeps_requisition_and_source(client, req):
    url = reverse("hiring:source_new")
    row = {
        "requisition": req.pk,
        "name": "A",
        "phone": "9876543210",
        "source": "Naukri",
    }
    r = client.post(url, row | {"again": "1"})
    assert r.status_code == 302 and f"requisition={req.pk}" in r["Location"]
    page = client.get(r["Location"]).content.decode()
    assert '<option value="Naukri" selected>' in page


def test_address_is_kept_on_a_new_card_only(client, req):
    url = reverse("hiring:source_new")
    row = {"requisition": req.pk, "name": "A", "phone": "9876543210"}
    client.post(url, row | {"address": "12 MG Road, Pune"})
    client.post(url, row | {"address": "somewhere else"})
    assert Person.objects.get().address == "12 MG Road, Pune"


def test_gender_is_kept_on_a_new_card(client, req):
    row = {"requisition": req.pk, "name": "A", "phone": "9876543210", "gender": "F"}
    client.post(reverse("hiring:source_new"), row)
    person = Person.objects.get()
    assert person.gender == "F"
    page = client.get(reverse("people:detail", args=[person.pk])).content.decode()
    assert "Female" in page


def test_sourced_numbers_are_called_tomorrow_and_a_repeat_reuses_the_last_card(
    req, caller
):
    from .services import next_day

    first = source_number(req, "Asha", "98765 43210", caller)
    call = FollowUp.objects.get()
    assert (call.purpose, call.due) == ("call", next_day())
    again = source_number(req, "Asha K", "9876543210", caller)
    assert again.is_duplicate and again.person == first.person
    assert FollowUp.objects.count() == 1  # already has a call waiting
    FollowUp.objects.update(status="completed")
    source_number(req, "Asha", "9876543210", caller)
    assert FollowUp.objects.filter(status="pending").count() == 1


def test_a_repeat_adds_no_call_when_another_card_with_the_number_has_one(req, caller):
    from people.models import Person

    old = source_number(req, "Asha", "9876543210", caller).person
    newer = Person.objects.create(
        company=req.company, name="Asha K", phone="9876543210"
    )
    assert newer.pk > old.pk and old.followups.filter(status="pending").exists()
    source_number(req, "Asha", "9876543210", caller)
    assert FollowUp.objects.filter(status="pending").count() == 1


def test_new_card_copies_department_and_source_from_the_requisition(req, caller):
    req.sub_department = "Elec + Mech"
    req.save()
    made = source_number(req, "Asha", "9876543210", caller, source="Naukri")
    p = made.person
    assert (p.department, p.sub_department, p.source_reference) == (
        "bo",
        "Elec + Mech",
        "Naukri",
    )


def test_free_or_paid_is_saved_on_the_card(client, req):
    client.post(
        reverse("hiring:source_new"),
        {"requisition": req.pk, "name": "A", "phone": "9876543210", "payment": "Paid"},
    )
    assert Person.objects.get().payment == "Paid"


def test_free_or_paid_on_a_repeat_number_updates_the_card(client, req):
    row = {"requisition": req.pk, "name": "A", "phone": "9876543210"}
    client.post(reverse("hiring:source_new"), row | {"payment": "Free"})
    client.post(reverse("hiring:source_new"), row | {"payment": "Paid"})
    assert Person.objects.count() == 1 and Person.objects.get().payment == "Paid"


def test_repeat_payment_reaches_every_card_with_the_number(client, req):
    for _ in range(2):  # two cards with one number, as the legacy import can leave
        Person.objects.create(
            company=req.company, name="A", phone="9876543210", payment="Free"
        )
    client.post(
        reverse("hiring:source_new"),
        {"requisition": req.pk, "name": "A", "phone": "9876543210", "payment": "Paid"},
    )
    assert set(Person.objects.values_list("payment", flat=True)) == {"Paid"}


def test_duplicate_popup_counts_followups_outcome_and_preference(client, req, caller):
    from django.utils import timezone

    from .models import Interview, Offer

    a = source_number(req, "A", "9000000001", caller).person
    b = source_number(req, "B", "9000000002", caller).person
    source_number(req, "C", "9000000003", caller)
    for n in ("9000000001", "9000000001", "9000000002", "9000000003"):
        source_number(req, "again", n, caller)  # A twice over still counts once
    FollowUp.objects.filter(person__in=[a, b]).update(status="completed")
    # C's follow-up stays pending: no call completed
    Interview.objects.create(
        person=a,
        requisition=req,
        scheduled_at=timezone.now(),
        result="hold_cftl",
        interviewer=caller,
    )
    Offer.objects.create(
        person=b,
        requisition=req,
        state="accepted",
        joining_date=timezone.localdate(),
        joined_on=timezone.localdate(),
        made_by=caller,
    )
    b.priority = "preferred"
    b.save()
    html = client.get(reverse("hiring:duplicates", args=[req.pk])).content.decode()
    assert "3 duplicate candidates" in html
    assert "4 duplicate numbers" in html  # the list counts rows, so say both
    from .services import duplicate_breakdown

    d = duplicate_breakdown(req)
    assert (d["followed"], d["not_followed"]) == (2, 1)
    assert d["numbers"] == 4
    assert dict(d["outcome"])["CFTL"] == dict(d["outcome"])["Joined"] == 1
    assert dict(d["outcome"])["No result yet"] == 1
    assert (
        dict(d["preference"])["Preferred"] == 1
        and dict(d["preference"])["Not set"] == 2
    )


def test_duplicate_popup_is_company_scoped(client, req, django_user_model):
    other = django_user_model.objects.create_user(username="X1", password="pw")
    client.force_login(other)
    assert client.get(reverse("hiring:duplicates", args=[req.pk])).status_code == 403


def test_duplicate_outcome_edge_cases(req, caller):
    from django.utils import timezone

    from .models import Interview, Offer
    from .services import duplicate_breakdown

    people = {}
    for n, name in enumerate(("rej", "acc", "off", "joined")):
        phone = f"900000010{n}"
        people[name] = source_number(req, name, phone, caller).person
        source_number(req, name, phone, caller)
    now = timezone.now()
    for result, when in (
        ("rejected", now),
        ("pending", now + timedelta(days=2)),
    ):
        Interview.objects.create(
            person=people["rej"],
            requisition=req,
            scheduled_at=when,
            result=result,
            interviewer=caller,
        )
    day = timezone.localdate()
    Offer.objects.create(
        person=people["acc"],
        requisition=req,
        state="accepted",
        joining_date=day,
        made_by=caller,
    )
    Offer.objects.create(person=people["off"], requisition=req, made_by=caller)
    Offer.objects.create(
        person=people["joined"],
        requisition=req,
        state="accepted",
        joining_date=day,
        joined_on=day,
        made_by=caller,
    )
    Offer.objects.create(person=people["joined"], requisition=req, made_by=caller)
    out = dict(duplicate_breakdown(req)["outcome"])
    assert out["Rejected"] == out["Accepted, not joined"] == out["Offered"] == 1
    assert out["Joined"] == 1 and out["Waiting for HR"] == 0
