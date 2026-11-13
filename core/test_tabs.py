import importlib

import pytest
from django.apps import apps
from django.template import Context, Template
from django.urls import reverse

from core.access import MODULES, first_tab_url, held_tabs
from core.models import AccessGrant, AccessLog, Company

pytestmark = pytest.mark.django_db

TABS = list(MODULES["recruitment"].sections)
PAGES = {
    "openings": "hiring:list",
    "people": "people:list",
    "sourcing": "hiring:sourcing",
    "screening": "hiring:screening",
    "calling": "hiring:calling",
    "selecting": "hiring:selecting",
    "hiring": "hiring:offers",
    "onboarding": "hiring:onboarding",
}


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def worker(client, django_user_model, senken):
    user = django_user_model.objects.create_user(username="w", password="pw")
    senken.memberships.create(user=user)
    client.force_login(user)
    return user


def give(user, company, *tabs, module="recruitment"):
    for tab in tabs:
        AccessGrant.objects.create(
            user=user, company=company, module=module, section=tab
        )


def test_the_nine_tabs():
    assert TABS == [
        "openings",
        "people",
        "sourcing",
        "screening",
        "calling",
        "selecting",
        "assessments",
        "hiring",
        "onboarding",
    ]


@pytest.mark.parametrize("tab,name", PAGES.items())
def test_each_tab_page_is_403_without_its_tab_and_200_with_it(
    client, worker, senken, tab, name
):
    give(worker, senken, *[t for t in TABS if t != tab])
    assert client.get(reverse(name)).status_code == 403
    AccessGrant.objects.all().delete()
    give(worker, senken, tab)
    assert client.get(reverse(name)).status_code == 200


def test_calling_only_user_cannot_open_screening_or_sourcing(client, worker, senken):
    give(worker, senken, "calling")
    assert client.get(reverse("hiring:calling")).status_code == 200
    assert client.get(reverse("hiring:screening")).status_code == 403
    assert client.get(reverse("hiring:sourcing")).status_code == 403
    assert client.get(reverse("hiring:call_new")).status_code != 403


def test_interview_review_needs_selecting_or_hiring(client, worker, senken):
    assert client.get(reverse("hiring:interview_review", args=[1])).status_code == 403
    give(worker, senken, "calling")
    assert client.get(reverse("hiring:interview_review", args=[1])).status_code == 403
    give(worker, senken, "selecting")
    assert client.get(reverse("hiring:interview_review", args=[1])).status_code == 404


def test_export_follows_its_tab(client, worker, senken):
    give(worker, senken, "calling")
    assert client.get(reverse("hiring:screening_export")).status_code == 403
    assert client.get(reverse("hiring:calling_export")).status_code == 200


def test_held_tabs_and_first_tab_url(worker, senken, django_user_model):
    give(worker, senken, "calling", "hiring")
    assert held_tabs(worker) == {"calling", "hiring"}
    assert first_tab_url(worker) == reverse("hiring:calling")
    boss = django_user_model.objects.create_user(
        username="b", password="pw", is_superuser=True
    )
    assert held_tabs(boss) == set(TABS)
    assert first_tab_url(boss) == reverse("hiring:list")


def test_assessments_only_has_no_landing_page(worker, senken):
    give(worker, senken, "assessments")
    assert first_tab_url(worker) is None


def test_inactive_user_holds_nothing(worker, senken):
    give(worker, senken, "calling")
    worker.is_active = False
    worker.save()
    assert held_tabs(worker) == set()


def test_grant_without_membership_holds_nothing(worker, senken):
    give(worker, senken, "calling")
    worker.memberships.all().delete()
    assert held_tabs(worker) == set()


def test_sidebar_link_leads_to_a_held_tab(client, worker, senken):
    give(worker, senken, "calling")
    html = client.get(reverse("home")).content.decode()
    assert f'href="{reverse("hiring:calling")}"' in html
    assert f'href="{reverse("people:list")}"' not in html


def test_no_tab_user_has_no_empanelment_link(client, worker):
    html = client.get(reverse("home")).content.decode()
    assert "Empanelment" not in html


def test_tab_bar_hides_tabs_not_held(client, worker, senken):
    give(worker, senken, "calling", "sourcing")
    html = client.get(reverse("hiring:calling")).content.decode()
    bar = html[html.index('aria-label="Empanelment sections"') :]
    bar = bar[: bar.index("</nav>")]
    assert reverse("hiring:sourcing") in bar and reverse("hiring:calling") in bar
    assert reverse("hiring:screening") not in bar
    assert reverse("hiring:report") not in bar
    assert reverse("people:list") not in bar


def _convert():
    return importlib.import_module("core.migrations.0012_access_tabs").convert


def _old(user, company, *sections):
    for section in sections:
        AccessGrant.objects.create(
            user=user, company=company, module="recruitment", section=section
        )


def test_migration_converts_candidates_to_seven_tabs(worker, senken):
    _old(worker, senken, "candidates", "openings", "assessments")
    _convert()(apps, None)
    assert set(
        AccessGrant.objects.filter(user=worker).values_list("section", flat=True)
    ) == {
        "openings",
        "assessments",
        "people",
        "sourcing",
        "screening",
        "calling",
        "selecting",
        "hiring",
        "onboarding",
    }
    log = AccessLog.objects.filter(action="grant", note="migrated")
    assert log.count() == 9 - 2  # only the seven that were created


def test_migration_is_idempotent(worker, senken):
    _old(worker, senken, "candidates")
    _convert()(apps, None)
    n = AccessGrant.objects.count()
    logs = AccessLog.objects.count()
    _convert()(apps, None)
    assert (AccessGrant.objects.count(), AccessLog.objects.count()) == (n, logs)


def test_interviews_maps_to_selecting_without_duplicate(worker, senken):
    _old(worker, senken, "interviews")
    _convert()(apps, None)
    assert list(
        AccessGrant.objects.filter(user=worker).values_list("section", flat=True)
    ) == ["selecting"]
    other = worker.__class__.objects.create_user(username="o", password="pw")
    senken.memberships.create(user=other)
    _old(other, senken, "candidates", "interviews")
    _convert()(apps, None)
    assert AccessGrant.objects.filter(user=other, section="selecting").count() == 1


def test_migration_leaves_other_modules_alone(worker, senken):
    give(worker, senken, "employees", module="hr")
    _convert()(apps, None)
    assert AccessGrant.objects.filter(module="hr", section="employees").exists()


def test_held_tabs_tag_renders():
    out = Template("{% load access_tags %}{% held_tabs as t %}{{ t|length }}").render(
        Context(
            {"user": type("U", (), {"is_active": False, "is_authenticated": True})()}
        )
    )
    assert out == "0"


@pytest.mark.parametrize("tab", ["calling", "screening"])
def test_either_calling_or_screening_can_work_a_followup(client, worker, senken, tab):
    give(worker, senken, tab)
    assert client.get(reverse("hiring:followup", args=[1])).status_code == 404


def test_neither_tab_cannot_work_a_followup(client, worker, senken):
    give(worker, senken, "sourcing")
    assert client.get(reverse("hiring:followup", args=[1])).status_code == 403
