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


def make(senken, user, **kw):
    kw = {"department": "bo", "profile": "MECH fitter", "headcount": 3} | kw
    return Requisition.objects.create(company=senken, opened_by=user, **kw)


def test_superadmin_releases_requisition(client, boss, senken):
    r = client.post(
        reverse("hiring:new"),
        {"department": "bo", "profile": "MECH fitter", "headcount": 3},
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
    data = {"department": "bo", "profile": "Electrician", "headcount": 2}
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
