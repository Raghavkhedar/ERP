from unittest import mock

import pytest
from django.core.exceptions import PermissionDenied

from core import matrix
from core.access import MODULES
from core.models import AccessGrant, AccessLog, AccessManager, Company

pytestmark = pytest.mark.django_db

TABS = list(MODULES["recruitment"].sections)
TAB = TABS[0]


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def avris():
    return Company.objects.get(slug="avris")


@pytest.fixture
def make(django_user_model, senken):
    def make(name, company=senken, **kwargs):
        user = django_user_model.objects.create_user(
            username=name, first_name=name, password="pw", **kwargs
        )
        if company:
            company.memberships.create(user=user)
        return user

    return make


@pytest.fixture
def boss(make):
    return make("boss", company=None, is_superuser=True)


@pytest.fixture
def manager(make, senken, boss):
    user = make("mgr")
    AccessManager.objects.create(user=user, company=senken, granted_by=boss)
    return user


@pytest.fixture
def ravi(make):
    return make("ravi")


def held(user, company):
    return set(
        AccessGrant.objects.filter(user=user, company=company).values_list(
            "section", flat=True
        )
    )


def test_superadmin_grants_and_revokes_a_tab(boss, ravi, senken):
    assert matrix.set_tab(boss, ravi, senken, "recruitment", TAB, True) is True
    assert held(ravi, senken) == {TAB}
    log = AccessLog.objects.get()
    assert (log.action, log.section, log.actor, log.subject) == (
        "grant",
        TAB,
        boss,
        ravi,
    )
    assert matrix.set_tab(boss, ravi, senken, "recruitment", TAB, False) is True
    assert held(ravi, senken) == set()
    assert AccessLog.objects.filter(action="revoke", section=TAB).count() == 1


def test_repeat_grant_writes_one_log_row(boss, ravi, senken):
    assert matrix.set_tab(boss, ravi, senken, "recruitment", TAB, True) is True
    assert matrix.set_tab(boss, ravi, senken, "recruitment", TAB, True) is False
    assert matrix.set_tab(boss, ravi, senken, "recruitment", TABS[1], False) is False
    assert AccessLog.objects.count() == 1


def test_manager_can_flip_tab_in_own_company(manager, ravi, senken):
    assert matrix.set_tab(manager, ravi, senken, "recruitment", TAB, True) is True
    assert AccessLog.objects.get().actor == manager


def test_manager_cannot_use_all_button(manager, ravi, senken):
    with pytest.raises(PermissionDenied):
        matrix.set_module(manager, ravi, senken, "recruitment", True)
    assert held(ravi, senken) == set()


def test_manager_cannot_edit_own_row(manager, senken):
    with pytest.raises(PermissionDenied):
        matrix.set_tab(manager, manager, senken, "recruitment", TAB, True)
    assert AccessLog.objects.count() == 0


def test_manager_of_senken_cannot_edit_avris(manager, make, avris):
    sam = make("sam", company=avris)
    with pytest.raises(PermissionDenied):
        matrix.set_tab(manager, sam, avris, "recruitment", TAB, True)


def test_demoted_manager_is_refused_next_call(boss, manager, ravi, senken):
    matrix.set_tab(manager, ravi, senken, "recruitment", TAB, True)
    matrix.remove_manager(boss, manager, senken)
    with pytest.raises(PermissionDenied):
        matrix.set_tab(manager, ravi, senken, "recruitment", TABS[1], True)


def test_deactivated_manager_is_refused(manager, ravi, senken):
    manager.is_active = False
    manager.save()
    assert matrix.can_manage(manager, senken) is False
    with pytest.raises(PermissionDenied):
        matrix.set_tab(manager, ravi, senken, "recruitment", TAB, True)


def test_manager_who_left_the_company_is_refused(manager, ravi, senken):
    manager.memberships.all().delete()
    with pytest.raises(PermissionDenied):
        matrix.set_tab(manager, ravi, senken, "recruitment", TAB, True)


@pytest.mark.parametrize("module,tab", [("nope", TAB), ("recruitment", "nope")])
def test_unknown_tab_or_module_raises_and_writes_nothing(
    boss, ravi, senken, module, tab
):
    with pytest.raises(matrix.MatrixError):
        matrix.set_tab(boss, ravi, senken, module, tab, True)
    assert AccessGrant.objects.count() == 0 and AccessLog.objects.count() == 0


def test_subject_outside_company_is_refused(boss, make, senken):
    outsider = make("out", company=None)
    with pytest.raises(matrix.MatrixError):
        matrix.set_tab(boss, outsider, senken, "recruitment", TAB, True)


def test_superadmin_and_inactive_subjects_are_refused(boss, make, ravi, senken):
    senken.memberships.create(user=boss)
    with pytest.raises(matrix.MatrixError):
        matrix.set_tab(boss, boss, senken, "recruitment", TAB, True)
    ravi.is_active = False
    ravi.save()
    with pytest.raises(matrix.MatrixError):
        matrix.set_tab(boss, ravi, senken, "recruitment", TAB, True)


def test_set_module_gives_every_tab_and_logs_once(boss, ravi, senken):
    assert matrix.set_module(boss, ravi, senken, "recruitment", True) == len(TABS)
    assert held(ravi, senken) == set(TABS)
    assert [log.action for log in AccessLog.objects.all()] == ["grant_module"]
    assert matrix.set_module(boss, ravi, senken, "recruitment", True) == 0
    assert AccessLog.objects.count() == 1
    assert matrix.set_module(boss, ravi, senken, "recruitment", False) == len(TABS)
    assert held(ravi, senken) == set()
    assert AccessLog.objects.filter(action="revoke_module").count() == 1


def test_only_superadmin_manages_managers(boss, manager, ravi, senken):
    with pytest.raises(PermissionDenied):
        matrix.add_manager(manager, ravi, senken)
    assert matrix.add_manager(boss, ravi, senken) is True
    assert matrix.add_manager(boss, ravi, senken) is False
    assert AccessLog.objects.filter(action="manager_add").count() == 1
    with pytest.raises(PermissionDenied):
        matrix.remove_manager(manager, ravi, senken)
    assert matrix.remove_manager(boss, ravi, senken) is True
    assert AccessLog.objects.filter(action="manager_remove").count() == 1


def test_grant_and_log_are_one_transaction(boss, ravi, senken):
    with mock.patch.object(AccessLog.objects, "create", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            matrix.set_tab(boss, ravi, senken, "recruitment", TAB, True)
    assert AccessGrant.objects.count() == 0


def test_log_keeps_names(boss, ravi, senken):
    matrix.set_tab(boss, ravi, senken, "recruitment", TAB, True)
    log = AccessLog.objects.get()
    assert (log.actor_name, log.subject_name) == ("boss", "ravi")


def test_drop_company_grants_logs_each_and_removes_manager(boss, manager, senken):
    matrix.set_module(boss, manager, senken, "recruitment", True)
    AccessLog.objects.all()  # history so far stays
    assert matrix.drop_company_grants(boss, manager, senken) == len(TABS)
    assert held(manager, senken) == set()
    assert not AccessManager.objects.filter(user=manager).exists()
    assert AccessLog.objects.filter(action="membership_removed").count() == len(TABS)
    assert AccessLog.objects.filter(action="manager_remove").count() == 1


def test_rows_lists_eligible_members_with_what_they_hold(
    boss, ravi, make, senken, avris
):
    senken.memberships.create(user=boss)
    gone = make("gone", is_active=False)
    sam = make("sam", company=avris)
    matrix.set_tab(boss, ravi, senken, "recruitment", TAB, True)
    rows = matrix.rows(senken)
    members = [r["user"] for r in rows]
    assert ravi in members and boss not in members
    assert gone not in members and sam not in members
    ravi_row = next(r for r in rows if r["user"] == ravi)
    assert ravi_row["held"] == {("recruitment", TAB)}
