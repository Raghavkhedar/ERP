import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from core.models import AccessGrant, AccessLog, AccessManager, Company

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def avris():
    return Company.objects.get(slug="avris")


@pytest.fixture
def make(django_user_model, senken):
    def make(name, *companies, **kwargs):
        user = django_user_model.objects.create_user(
            username=name, first_name=name, password="pw", **kwargs
        )
        for company in companies if companies else [senken]:
            company.memberships.create(user=user)
        return user

    return make


@pytest.fixture
def boss(make):
    return make("S1", is_superuser=True)


@pytest.fixture
def manager(make, senken, boss):
    user = make("S2")
    AccessManager.objects.create(user=user, company=senken, granted_by=boss)
    return user


@pytest.fixture
def ravi(make):
    return make("S3")


def names(response):
    return [r["user"].first_name for r in response.context["rows"]]


def post_cell(client, user, company, tab="calling", on="1", module="recruitment"):
    return client.post(
        reverse("access_matrix_cell"),
        {
            "user": user.pk,
            "company": company.slug,
            "module": module,
            "tab": tab,
            "on": on,
        },
    )


def test_non_manager_gets_403(client, make):
    plain = make("S9")
    client.force_login(plain)
    assert client.get(reverse("access_matrix")).status_code == 403
    admin = make("S8")
    admin.groups.add(Group.objects.get_or_create(name="Office admin")[0])
    client.force_login(admin)
    assert client.get(reverse("access_matrix")).status_code == 403


def test_anonymous_is_sent_to_login(client):
    assert client.get(reverse("access_matrix")).status_code == 302


def test_superadmin_sees_company_switch_with_exactly_two_options(client, boss):
    client.force_login(boss)
    page = client.get(reverse("access_matrix"))
    assert {c.slug for c in page.context["companies"]} == {"senken", "avris"}
    assert len(page.context["companies"]) == 2
    assert page.context["company"].slug in {"senken", "avris"}


def test_unmanaged_company_is_403_not_fallback(client, manager):
    client.force_login(manager)
    assert client.get(reverse("access_matrix"), {"company": "avris"}).status_code == 403
    assert client.get(reverse("access_matrix"), {"company": "nope"}).status_code == 403


def test_manager_sees_only_their_company_rows(client, manager, ravi, make, avris):
    make("S4", avris)
    client.force_login(manager)
    page = client.get(reverse("access_matrix"))
    assert page.context["company"].slug == "senken"
    assert [c.slug for c in page.context["companies"]] == ["senken"]
    assert "S4" not in names(page) and "S3" in names(page)


def test_shared_employee_grid_shows_only_selected_company_tabs(
    client, boss, make, senken, avris
):
    shared = make("S381", senken, avris)
    AccessGrant.objects.create(
        user=shared, company=avris, module="recruitment", section="calling"
    )
    client.force_login(boss)
    senken_row = client.get(reverse("access_matrix"), {"company": "senken"}).context[
        "rows"
    ]
    avris_row = client.get(reverse("access_matrix"), {"company": "avris"}).context[
        "rows"
    ]
    assert next(r for r in senken_row if r["user"] == shared)["held"] == set()
    assert next(r for r in avris_row if r["user"] == shared)["held"] == {
        ("recruitment", "calling")
    }


def test_superadmin_and_inactive_are_not_rows(client, boss, make):
    make("S5", is_active=False)
    client.force_login(boss)
    page = client.get(reverse("access_matrix"), {"company": "senken"})
    assert "S1" not in names(page) and "S5" not in names(page)


def test_search_filters_people(client, boss, ravi, make):
    make("S4")
    client.force_login(boss)
    page = client.get(reverse("access_matrix"), {"company": "senken", "q": "s3"})
    assert names(page) == ["S3"]


def test_cell_post_flips_and_logs(client, boss, ravi, senken):
    client.force_login(boss)
    response = post_cell(client, ravi, senken)
    assert response.status_code == 200
    assert AccessGrant.objects.filter(user=ravi, section="calling").exists()
    assert AccessLog.objects.get().action == "grant"
    post_cell(client, ravi, senken, on="0")
    assert not AccessGrant.objects.exists()
    assert AccessLog.objects.count() == 2


def test_cell_row_reply_shows_the_new_state(client, boss, ravi, senken):
    client.force_login(boss)
    html = post_cell(client, ravi, senken).content.decode()
    assert html.lstrip().startswith("<tr")
    assert 'aria-pressed="true"' in html


def test_manager_can_flip_a_cell(client, manager, ravi, senken):
    client.force_login(manager)
    assert post_cell(client, ravi, senken).status_code == 200


@pytest.mark.parametrize(
    "kwargs", [{"tab": "nope"}, {"module": "nope"}, {"module": "hr", "tab": "payroll"}]
)
def test_cell_post_nonexistent_tab_or_module_is_400_and_no_row(
    client, boss, ravi, senken, kwargs
):
    client.force_login(boss)
    assert post_cell(client, ravi, senken, **kwargs).status_code == 400
    assert not AccessGrant.objects.exists() and not AccessLog.objects.exists()


def test_cell_post_bad_on_value_is_400(client, boss, ravi, senken):
    client.force_login(boss)
    assert post_cell(client, ravi, senken, on="maybe").status_code == 400


def test_cell_post_user_from_other_company_is_400(client, boss, make, senken, avris):
    outsider = make("S6", avris)
    client.force_login(boss)
    assert post_cell(client, outsider, senken).status_code == 400
    assert not AccessGrant.objects.exists()


def test_cell_post_unknown_company_or_user_is_404(client, boss, ravi, senken):
    client.force_login(boss)
    bad = client.post(
        reverse("access_matrix_cell"),
        {
            "user": ravi.pk,
            "company": "nope",
            "module": "recruitment",
            "tab": "calling",
            "on": "1",
        },
    )
    assert bad.status_code == 404
    gone = client.post(
        reverse("access_matrix_cell"),
        {
            "user": 99999,
            "company": "senken",
            "module": "recruitment",
            "tab": "calling",
            "on": "1",
        },
    )
    assert gone.status_code == 404


def test_manager_cannot_edit_other_company_or_own_row(
    client, manager, make, senken, avris
):
    client.force_login(manager)
    assert post_cell(client, manager, senken).status_code == 403
    assert post_cell(client, make("S7", avris), avris).status_code == 403


def test_manager_post_to_all_button_is_403(client, manager, ravi, senken):
    client.force_login(manager)
    response = client.post(
        reverse("access_matrix_module"),
        {"user": ravi.pk, "company": "senken", "module": "recruitment", "on": "1"},
    )
    assert response.status_code == 403
    assert not AccessGrant.objects.exists()


def test_superadmin_all_button_gives_whole_module(client, boss, ravi, senken):
    client.force_login(boss)
    response = client.post(
        reverse("access_matrix_module"),
        {"user": ravi.pk, "company": "senken", "module": "recruitment", "on": "1"},
    )
    assert response.status_code == 200
    assert AccessGrant.objects.filter(user=ravi).count() == 9
    assert AccessLog.objects.get().action == "grant_module"


def test_manager_page_has_no_all_button(client, manager, boss, ravi):
    client.force_login(manager)
    page = reverse("access_matrix") + "?company=senken"
    assert b"access/matrix/module/" not in client.get(page).content
    client.force_login(boss)
    assert b"access/matrix/module/" in client.get(page).content


def test_get_on_post_endpoints_is_405(client, boss):
    client.force_login(boss)
    assert client.get(reverse("access_matrix_cell")).status_code == 405
    assert client.get(reverse("access_matrix_module")).status_code == 405


def test_removed_manager_loses_the_page_at_once(client, manager, senken):
    client.force_login(manager)
    assert client.get(reverse("access_matrix")).status_code == 200
    AccessManager.objects.all().delete()
    assert client.get(reverse("access_matrix")).status_code == 403


def test_matrix_link_shows_only_to_those_who_may_open_it(client, boss, manager, ravi):
    link = f'href="{reverse("access_matrix")}"'
    for user, shown in ((boss, True), (manager, True), (ravi, False)):
        client.force_login(user)
        assert (link in client.get(reverse("home")).content.decode()) is shown
