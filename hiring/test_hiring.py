import pytest
from django.urls import reverse

from core.models import AccessGrant, Company

from .models import Requisition

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def boss(client, django_user_model, senken):
    user = django_user_model.objects.create_superuser(username="S1", password="pw")
    senken.memberships.create(user=user)
    client.force_login(user)
    session = client.session
    session["company"] = "senken"
    session.save()
    return user


@pytest.fixture
def reader(client, django_user_model, senken):
    user = django_user_model.objects.create_user(username="S9", password="pw")
    senken.memberships.create(user=user)
    AccessGrant.objects.create(
        user=user, company=senken, module="recruitment", section="openings"
    )
    client.force_login(user)
    return user


REQUIRED = {"kind": "new", "employment": "permanent", "urgency": "not_urgent"}


def make(senken, user, **kw):
    kw = {"department": "bo", "profile": "MECH fitter", "headcount": 3} | kw
    return Requisition.objects.create(company=senken, opened_by=user, **kw)


def test_superadmin_releases_requisition(client, boss, senken):
    r = client.post(
        reverse("hiring:new"),
        REQUIRED | {"department": "bo", "profile": "MECH fitter", "headcount": 3},
    )
    assert r.status_code == 302
    req = Requisition.objects.get()
    assert (req.opened_by, req.company, req.status) == (boss, senken, "open")


def test_reader_can_list_and_export_but_not_release(client, boss, reader, senken):
    make(senken, boss)
    assert b"MECH fitter" in client.get(reverse("hiring:list")).content
    assert client.get(reverse("hiring:export")).status_code == 200
    assert client.get(reverse("hiring:new")).status_code == 403
    assert client.post(reverse("hiring:new"), {}).status_code == 403


def test_zero_headcount_rejected(client, boss):
    r = client.post(
        reverse("hiring:new"), {"department": "bo", "profile": "x", "headcount": 0}
    )
    assert r.status_code == 200
    assert not Requisition.objects.exists()


def test_stale_edit_is_rejected(client, boss, senken):
    req = make(senken, boss)
    data = REQUIRED | {"department": "bo", "profile": "Electrician", "headcount": 2}
    client.post(reverse("hiring:edit", args=[req.pk]), data | {"version": 1})
    client.post(
        reverse("hiring:edit", args=[req.pk]), data | {"profile": "Late", "version": 1}
    )
    req.refresh_from_db()
    assert (req.profile, req.version) == ("Electrician", 2)


def test_close_keeps_the_row(client, boss, senken):
    req = make(senken, boss)
    client.post(reverse("hiring:close", args=[req.pk]))
    req.refresh_from_db()
    assert req.status == "closed"


def test_sidebar_lights_empanelment_on_preparing(client, boss):
    page = client.get(reverse("hiring:list")).content.decode()
    assert 'title="Empanelment" aria-current="page"' in page


def test_requisition_form_fields_and_priority_order(client, boss, senken):
    client.post(
        reverse("hiring:new"),
        {
            "kind": "backfill",
            "department": "bo",
            "sub_department": "Accounts",
            "profile": "Accountant",
            "headcount": 1,
            "employment": "permanent",
            "urgency": "fire_fighting",
            "languages": ["Hindi", "English"],
            "exposure": "high",
        },
    )
    make(senken, boss, urgency="urgent", profile="Urgent one")
    make(senken, boss, profile="Calm one")
    r = Requisition.objects.get(profile="Accountant")
    assert (r.kind, r.sub_department, r.languages) == (
        "backfill",
        "Accounts",
        ["Hindi", "English"],
    )
    page = client.get(reverse("hiring:list")).content.decode()
    assert page.index("Accountant") < page.index("Urgent one") < page.index("Calm one")


def _req(boss, senken):
    return Requisition.objects.create(
        company=senken,
        department="bo",
        profile="Data Analyst",
        headcount=1,
        opened_by=boss,
    )


def test_discussion_comment_and_job_post(client, boss, senken):
    r = _req(boss, senken)
    url = reverse("hiring:post", args=[r.pk])
    assert client.post(url, {"body": "Need it by Friday"}).status_code == 302
    job = {
        "portal": "Job Hai",
        "keyword": "Data Analyst Intern",
        "posted_on": "2026-10-29",
        "post_status": "active",
        "payment": "free",
        "portal_user": "nish.S@senkenindia.in",
        "posting_company": Company.objects.get(slug="senken").name,
    }
    assert client.post(url, job).status_code == 302
    assert [p.is_job_post for p in r.posts.all()] == [False, True]
    page = client.get(reverse("hiring:detail", args=[r.pk]))
    assert b"Job post on Job Hai" in page.content


def test_discussion_rejects_empty_and_incomplete(client, boss, senken):
    r = _req(boss, senken)
    url = reverse("hiring:post", args=[r.pk])
    assert client.post(url, {"body": "  "}).status_code == 422
    assert client.post(url, {"portal": "Job Hai"}).status_code == 422
    assert r.posts.count() == 0


def test_reader_can_join_discussion(client, boss, reader, senken):
    r = _req(boss, senken)
    url = reverse("hiring:post", args=[r.pk])
    assert client.post(url, {"body": "On it"}).status_code == 302
    assert r.posts.get().author == reader


def test_by_when_days_sets_the_date_and_reopening_keeps_it(client, boss, senken):
    from datetime import timedelta

    from django.utils import timezone

    url = reverse("hiring:new")
    client.post(
        url,
        REQUIRED
        | {"department": "bo", "profile": "Fitter", "headcount": 1, "days": 10},
    )
    r = Requisition.objects.get()
    assert r.needed_by == timezone.localdate() + timedelta(days=10)
    # Saving with the number the form showed leaves the date alone.
    r.needed_by = timezone.localdate() + timedelta(days=4)
    r.save()
    data = REQUIRED | {"department": "bo", "profile": "Fitter", "headcount": 1}
    client.post(
        reverse("hiring:edit", args=[r.pk]), data | {"days": 4, "version": r.version}
    )
    r.refresh_from_db()
    assert r.needed_by == timezone.localdate() + timedelta(days=4)


def test_job_post_on_a_portal_not_in_the_list(client, boss, senken):
    r = _req(boss, senken)
    url = reverse("hiring:post", args=[r.pk])
    job = {
        "portal": "other",
        "keyword": "Data Analyst",
        "posted_on": "2026-10-29",
        "post_status": "active",
        "payment": "free",
    }
    assert client.post(url, job).status_code == 422  # name missing
    assert (
        client.post(url, job | {"portal_other": "Local Jobs Board"}).status_code == 302
    )
    assert r.posts.get().portal == "Local Jobs Board"


def test_job_post_company_is_senken_or_avris(client, boss, senken):
    r = _req(boss, senken)
    url = reverse("hiring:post", args=[r.pk])
    job = {
        "portal": "Naukri",
        "keyword": "x",
        "posted_on": "2026-10-29",
        "post_status": "active",
        "payment": "free",
    }
    assert client.post(url, job | {"posting_company": "Acme"}).status_code == 422
    avris = Company.objects.get(slug="avris").name
    assert client.post(url, job | {"posting_company": avris}).status_code == 302
    assert r.posts.get().posting_company == avris
