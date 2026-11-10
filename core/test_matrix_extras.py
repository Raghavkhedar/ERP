from io import BytesIO

import pytest
from django.urls import reverse
from openpyxl import load_workbook

from core import matrix
from core.models import AccessLog, AccessManager, Company

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


def page(client, **params):
    return client.get(reverse("access_matrix"), {"company": "senken", **params})


def manage(client, user, action, company="senken"):
    return client.post(
        reverse("access_matrix_managers"),
        {"user": user.pk, "company": company, "action": action},
    )


def sheet(response, name):
    book = load_workbook(BytesIO(response.content))
    return [[c.value for c in row] for row in book[name].iter_rows()]


def test_manager_strip_visible_only_to_superadmin(client, boss, manager):
    client.force_login(boss)
    assert b"access/matrix/managers/" in page(client).content
    client.force_login(manager)
    assert b"access/matrix/managers/" not in page(client).content


def test_add_manager_logs_and_gives_page_access(client, boss, ravi, senken):
    client.force_login(boss)
    assert manage(client, ravi, "add").status_code == 302
    assert AccessLog.objects.get().action == "manager_add"
    client.force_login(ravi)
    assert page(client).status_code == 200


def test_remove_manager_removes_page_access_immediately(client, boss, manager):
    client.force_login(boss)
    assert manage(client, manager, "remove").status_code == 302
    client.force_login(manager)
    assert page(client).status_code == 403


def test_manager_cannot_add_manager(client, manager, ravi):
    client.force_login(manager)
    assert manage(client, ravi, "add").status_code == 403
    assert not AccessManager.objects.filter(user=ravi).exists()


def test_manager_post_bad_action_or_outsider_is_400(client, boss, make, avris):
    outsider = make("S6", avris)
    client.force_login(boss)
    assert manage(client, outsider, "add").status_code == 400
    assert manage(client, outsider, "explode").status_code == 400


def test_history_lists_newest_first_and_pages(client, boss, ravi, senken):
    client.force_login(boss)
    for i in range(30):
        matrix.set_tab(boss, ravi, senken, "recruitment", "calling", i % 2 == 0)
    first = page(client)
    assert len(first.context["history"]) == 25
    entries = list(first.context["history"])
    assert entries[0].created_at >= entries[-1].created_at
    assert len(page(client, page=2).context["history"]) == 5


def test_manager_history_only_own_company(client, manager, boss, make, senken, avris):
    sam = make("S4", avris)
    matrix.set_tab(boss, sam, avris, "recruitment", "calling", True)
    ravi = make("S5")
    matrix.set_tab(boss, ravi, senken, "recruitment", "calling", True)
    client.force_login(manager)
    shown = list(page(client).context["history"])
    assert [e.subject_name for e in shown] == ["S5"]


def test_history_lines_survive_deleted_users(client, boss, ravi, senken):
    matrix.set_tab(boss, ravi, senken, "recruitment", "calling", True)
    ravi.delete()
    client.force_login(boss)
    html = page(client).content.decode()
    assert "S3" in html


def test_export_matches_grid(client, boss, ravi, senken):
    matrix.set_tab(boss, ravi, senken, "recruitment", "calling", True)
    client.force_login(boss)
    response = client.get(reverse("access_matrix_export"), {"company": "senken"})
    rows = sheet(response, "Matrix")
    header = rows[0]
    me = next(r for r in rows if r[0] == "S3")
    assert me[header.index("Calling")] == "Yes"
    assert me[header.index("Sourcing")] in (None, "")


def test_history_export_has_the_log(client, boss, ravi, senken):
    matrix.set_tab(boss, ravi, senken, "recruitment", "calling", True)
    client.force_login(boss)
    response = client.get(
        reverse("access_matrix_history_export"), {"company": "senken"}
    )
    rows = sheet(response, "History")
    assert rows[0][:3] == ["When", "Who", "Whom"]
    assert rows[1][1:3] == ["S1", "S3"]


def test_exports_403_for_non_managers_and_other_companies(client, ravi, manager):
    client.force_login(ravi)
    for name in ("access_matrix_export", "access_matrix_history_export"):
        assert client.get(reverse(name), {"company": "senken"}).status_code == 403
    client.force_login(manager)
    for name in ("access_matrix_export", "access_matrix_history_export"):
        assert client.get(reverse(name), {"company": "avris"}).status_code == 403


def test_export_cells_escape_formulas(client, boss, make, senken):
    odd = make("S7")
    odd.first_name = "=cmd"
    odd.save()
    client.force_login(boss)
    rows = sheet(
        client.get(reverse("access_matrix_export"), {"company": "senken"}), "Matrix"
    )
    assert not any(str(r[1]).startswith("=") for r in rows[1:])
