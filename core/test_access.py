import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.test import RequestFactory
from django.urls import reverse

from core.access import (
    can_grant,
    companies_with_access,
    has_module,
    require_section,
    scope,
)
from core.models import AccessGrant, Company, Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def avris():
    return Company.objects.get(slug="avris")


@pytest.fixture
def make(django_user_model):
    def make(name, **kwargs):
        return django_user_model.objects.create_user(
            username=name, first_name=name, password="pw", **kwargs
        )

    return make


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_superuser(
        username="boss", first_name="boss", password="pw"
    )


@pytest.fixture
def admin(make):
    user = make("admin")
    user.groups.add(Group.objects.get(name="Office admin"))
    return user


def grant(user, company, module="finance", section="ledger"):
    Membership.objects.get_or_create(user=user, company=company)
    return AccessGrant.objects.create(
        user=user, company=company, module=module, section=section
    )


def test_both_companies_exist():
    assert set(Company.objects.values_list("slug", flat=True)) == {"senken", "avris"}


def test_nothing_is_open_without_a_grant(make, senken):
    user = make("e1")
    Membership.objects.create(user=user, company=senken)
    assert not has_module(user, "hr")
    assert not companies_with_access(user, "hr", "employees").exists()


def test_a_grant_opens_only_its_section_and_company(make, senken, avris):
    user = make("e1")
    grant(user, senken, "hr", "employees")
    Membership.objects.create(user=user, company=avris)
    assert has_module(user, "hr")
    assert list(companies_with_access(user, "hr", "employees")) == [senken]
    assert not companies_with_access(user, "hr", "payroll").exists()


def test_a_grant_stops_counting_once_the_membership_ends(make, senken):
    user = make("e1")
    grant(user, senken, "hr", "employees")
    Membership.objects.filter(user=user).delete()
    assert not has_module(user, "hr")


def test_superuser_opens_everything(boss):
    assert has_module(boss, "finance")
    assert companies_with_access(boss, "finance", "ledger").count() == 2


def test_only_superadmin_hands_out_finance(boss, admin):
    assert can_grant(boss, "finance")
    assert not can_grant(admin, "finance")
    assert can_grant(admin, "hr")


def test_require_section_returns_403_without_access(make, senken):
    user = make("e1")
    request = RequestFactory().get("/")
    request.user = user
    request.session = {}
    with pytest.raises(PermissionDenied):
        require_section("finance", "ledger")(lambda r: None)(request)


def test_require_section_narrows_to_the_switcher_choice(make, senken, avris):
    user = make("e1")
    grant(user, senken)
    grant(user, avris)
    request = RequestFactory().get("/")
    request.user = user
    request.session = {"company": "avris"}
    assert list(scope(request, "finance", "ledger")) == [avris]
    request.session = {"company": "all"}
    assert set(scope(request, "finance", "ledger")) == {senken, avris}


def test_the_shared_employee_is_paid_by_avris(django_user_model):
    # The migration only knows S381 if the account exists when it runs, so
    # exercise the same rule the seed applies.
    user = django_user_model.objects.create_user(username="S381", first_name="a")
    senken, avris = (
        Company.objects.get(slug="senken"),
        Company.objects.get(slug="avris"),
    )
    Membership.objects.create(user=user, company=senken)
    Membership.objects.create(user=user, company=avris, pays_salary=True)
    assert user.memberships.get(pays_salary=True).company == avris


def test_only_one_company_can_pay(make, senken, avris):
    user = make("e1")
    Membership.objects.create(user=user, company=senken, pays_salary=True)
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=user, company=avris, pays_salary=True)


def test_access_pages_are_for_office_admins(client, make):
    user = make("e1")
    client.force_login(user)
    assert client.get(reverse("access_people")).status_code == 403
    assert client.get(reverse("access_person", args=[user.pk])).status_code == 403


def test_admin_adds_a_company_and_grants_hr_but_not_finance(
    client, admin, make, senken
):
    target = make("e1")
    client.force_login(admin)
    url = reverse("access_person", args=[target.pk])
    client.post(
        url, {"action": "companies", "company": ["senken"], "paid_by": "senken"}
    )
    assert target.memberships.get().pays_salary
    client.post(
        url,
        {"action": "access", "grant": ["hr:employees:senken", "finance:ledger:senken"]},
    )
    held = set(target.access_grants.values_list("module", "section"))
    assert held == {("hr", "employees")}


def test_superuser_can_grant_finance_and_admin_cannot_remove_it(
    client, boss, admin, make, senken
):
    target = make("e1")
    client.force_login(boss)
    url = reverse("access_person", args=[target.pk])
    client.post(url, {"action": "companies", "company": ["senken"]})
    client.post(url, {"action": "access", "grant": ["finance:reports:senken"]})
    assert target.access_grants.filter(module="finance").count() == 1
    client.force_login(admin)
    client.post(url, {"action": "access", "grant": []})
    assert target.access_grants.filter(module="finance").count() == 1


def test_dropping_a_company_drops_its_grants(client, admin, make, senken, avris):
    target = make("e1")
    client.force_login(admin)
    url = reverse("access_person", args=[target.pk])
    client.post(url, {"action": "companies", "company": ["senken", "avris"]})
    client.post(
        url, {"action": "access", "grant": ["hr:leave:avris", "hr:leave:senken"]}
    )
    client.post(url, {"action": "companies", "company": ["senken"]})
    assert list(target.access_grants.values_list("company__slug", flat=True)) == [
        "senken"
    ]


def test_switching_company_only_to_ones_you_belong_to(client, make, senken, avris):
    user = make("e1")
    Membership.objects.create(user=user, company=senken)
    client.force_login(user)
    client.post(reverse("switch_company"), {"company": "avris", "next": "/"})
    assert "company" not in client.session
    client.post(
        reverse("switch_company"), {"company": "senken", "next": "https://evil.example"}
    )
    assert client.session["company"] == "senken"


def test_admin_page_lists_people_and_shows_the_switcher(
    client, admin, make, senken, avris
):
    both = make("e1")
    Membership.objects.create(user=both, company=senken)
    Membership.objects.create(user=both, company=avris)
    client.force_login(both)
    assert "All companies" in client.get("/").content.decode()
    client.force_login(admin)
    assert "e1" in client.get(reverse("access_people")).content.decode()


@pytest.mark.django_db(transaction=True)
def test_seed_migration_puts_everyone_in_senken_and_s381_in_avris_too():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    executor.migrate([("core", "0008_user_supervisor")])
    old = executor.loader.project_state([("core", "0008_user_supervisor")]).apps
    User = old.get_model("core", "User")
    User.objects.create(username="S381", first_name="Anushman")
    User.objects.create(username="S1", first_name="Other")

    executor = MigrationExecutor(connection)
    executor.migrate([("core", "0010_seed_companies")])
    new = executor.loader.project_state([("core", "0010_seed_companies")]).apps
    Membership = new.get_model("core", "Membership")
    pairs = set(
        Membership.objects.values_list("user__username", "company__slug", "pays_salary")
    )
    assert pairs >= {
        ("S1", "senken", True),
        ("S381", "senken", False),
        ("S381", "avris", True),
    }
    assert ("S1", "avris", True) not in pairs and ("S1", "avris", False) not in pairs
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
