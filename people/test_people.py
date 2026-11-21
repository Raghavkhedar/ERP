import pytest
from django.urls import reverse

from core.access import MODULES
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
    for tab in MODULES["recruitment"].sections:
        AccessGrant.objects.create(
            user=user, company=senken, module="recruitment", section=tab
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


def test_sidebar_can_collapse_to_a_rail(client, caller):
    page = client.get(reverse("home")).content.decode()
    assert "nav-rail" in page and 'aria-label="Collapse or expand the sidebar"' in page


def test_card_lists_archived_cards_that_share_its_number(client, caller, senken):
    main = make(senken)
    gone = make(senken, name="Old copy", phone="9876543210")
    gone.archived_at = gone.created_at
    gone.save()
    page = client.get(reverse("people:detail", args=[main.pk])).content.decode()
    assert "Old copy" in page


def test_list_searches_the_extra_numbers(client, caller, senken):
    make(
        senken, "Ravi", "9111111111", alternate_phone="8285424619", phone_3="7000000001"
    )
    for n in ("8285424619", "7000000001"):
        assert "Ravi" in client.get(reverse("people:list"), {"q": n}).content.decode()


def test_search_and_card_page_reach_archived_cards(client, caller, senken):
    from django.utils import timezone

    old = make(senken, "Hidden", "8285424619", archived_at=timezone.now())
    assert "Hidden" not in client.get(reverse("people:list")).content.decode()
    page = client.get(reverse("people:list"), {"q": "8285424619"}).content.decode()
    assert "Hidden" in page and "Archived" in page
    assert client.get(reverse("people:detail", args=[old.pk])).status_code == 200


def test_archived_card_can_be_restored_but_not_edited_and_export_skips_it(
    client, caller, senken
):
    from django.utils import timezone

    old = make(senken, "Hidden", "8285424619", archived_at=timezone.now())
    assert client.get(reverse("people:edit", args=[old.pk])).status_code == 404
    export = client.get(reverse("people:export"), {"q": "8285424619"})
    from io import BytesIO

    from openpyxl import load_workbook

    cells = [c.value for r in load_workbook(BytesIO(export.content)).active for c in r]
    assert "Hidden" not in cells
    client.post(reverse("people:unarchive", args=[old.pk]))
    old.refresh_from_db()
    assert old.archived_at is None


def test_admin_lists_archived_cards_and_is_read_only(client, django_user_model, senken):
    from django.utils import timezone

    admin = django_user_model.objects.create_superuser("root", password="pw")
    client.force_login(admin)
    old = make(senken, "Hidden", "8285424619", archived_at=timezone.now())
    url = reverse("admin:people_person_changelist")
    assert "Hidden" in client.get(url, {"q": "8285424619"}).content.decode()
    assert (
        client.get(reverse("admin:people_person_change", args=[old.pk])).status_code
        == 200
    )
    assert client.get(reverse("admin:people_person_add")).status_code == 403
    assert (
        client.post(reverse("admin:people_person_delete", args=[old.pk])).status_code
        == 403
    )
    for model in ("requisition", "followup", "calllog", "interview", "offer"):
        page = client.get(reverse(f"admin:hiring_{model}_changelist"), {"q": "x"})
        assert page.status_code == 200


@pytest.mark.django_db
def test_backfill_numbers_empty_cards_after_the_highest(django_db_blocker):
    import importlib

    from django.apps import apps as real_apps

    from core.models import Company

    mod = importlib.import_module("people.migrations.0006_backfill_candidate_ids")
    senken = Company.objects.get(slug="senken")
    Person.objects.create(company=senken, name="Old", phone="1", candidate_id="WJ7")
    a = Person.objects.create(company=senken, name="A", phone="2")
    b = Person.objects.create(company=senken, name="B", phone="3")
    mod.backfill(real_apps, None)
    a.refresh_from_db(), b.refresh_from_db()
    assert (a.candidate_id, b.candidate_id) == ("WJ8", "WJ9")
