import pytest
from django.urls import reverse

from core.models import AccessGrant, Company

from .models import Person, phone_key

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def caller(client, django_user_model, senken):
    """A BO Caller: granted Empanelment candidates in Senken only."""
    user = django_user_model.objects.create_user(username="S9", password="pw")
    senken.memberships.create(user=user)
    AccessGrant.objects.create(
        user=user, company=senken, module="recruitment", section="candidates"
    )
    client.force_login(user)
    return user


def make(company, name="Asha", phone="+91 98765 43210", **kw):
    return Person.objects.create(company=company, name=name, phone=phone, **kw)


def test_phone_key_is_last_ten_digits():
    assert phone_key("+91 98765-43210") == phone_key("09876543210") == "9876543210"


def test_same_number_links_cards_without_merging(senken):
    a, b = make(senken), make(senken, name="Asha K", phone="9876543210")
    assert list(a.same_number()) == [b]
    assert Person.objects.count() == 2


def test_list_needs_access(client, django_user_model):
    client.force_login(
        django_user_model.objects.create_user(username="S8", password="pw")
    )
    assert client.get(reverse("people:list")).status_code == 403


def test_list_searches_by_phone_in_any_spelling(client, caller, senken):
    make(senken)
    make(senken, name="Ravi", phone="9000000001")
    page = client.get(reverse("people:list"), {"q": "98765 43210"[:5]}).content.decode()
    assert "Asha" in page and "Ravi" not in page


def test_other_company_cards_stay_hidden(client, caller):
    other = make(Company.objects.get(slug="avris"))
    assert client.get(reverse("people:detail", args=[other.pk])).status_code == 404


def test_add_candidate(client, caller, senken):
    resp = client.post(
        reverse("people:new"),
        {"name": "Asha", "phone": "98765 43210", "contact_status": "active"},
    )
    assert resp.status_code == 302
    assert Person.objects.get().company == senken


def test_short_phone_rejected(client, caller):
    resp = client.post(
        reverse("people:new"),
        {"name": "Asha", "phone": "123", "contact_status": "active"},
    )
    assert resp.status_code == 200 and not Person.objects.exists()


def test_stale_edit_is_rejected(client, caller, senken):
    p = make(senken)
    form = {
        "name": "Asha",
        "phone": p.phone,
        "contact_status": "active",
        "version": p.version,
    }
    assert (
        client.post(
            reverse("people:edit", args=[p.pk]), {**form, "name": "First"}
        ).status_code
        == 302
    )
    client.post(reverse("people:edit", args=[p.pk]), {**form, "name": "Second"})
    p.refresh_from_db()
    assert p.name == "First" and p.version == 2


def test_archive_keeps_the_card(client, caller, senken):
    p = make(senken)
    client.post(reverse("people:archive", args=[p.pk]))
    p.refresh_from_db()
    assert p.archived_at and client.get(reverse("people:list")).context["total"] == 0


def test_export(client, caller, senken):
    make(senken)
    resp = client.get(reverse("people:export"))
    assert resp.status_code == 200 and "spreadsheetml" in resp["Content-Type"]


def test_sidebar_lists_empanelment_only_for_those_with_access(
    client, caller, django_user_model
):
    assert "Empanelment" in client.get(reverse("home")).content.decode()
    client.force_login(
        django_user_model.objects.create_user(username="S7", password="pw")
    )
    assert "Empanelment" not in client.get(reverse("home")).content.decode()
