import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from core.models import AccessGrant, AccessLog, AccessManager, Company, Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def avris():
    return Company.objects.get(slug="avris")


@pytest.fixture
def admin(django_user_model):
    user = django_user_model.objects.create_user(
        username="S1", first_name="Admin", password="pw"
    )
    user.groups.add(Group.objects.get(name="Office admin"))
    return user


@pytest.fixture
def worker(django_user_model, senken, avris):
    user = django_user_model.objects.create_user(
        username="S2", first_name="Worker", password="pw"
    )
    Membership.objects.create(user=user, company=senken, pays_salary=True)
    Membership.objects.create(user=user, company=avris)
    for company in (senken, avris):
        for tab in ("calling", "sourcing"):
            AccessGrant.objects.create(
                user=user, company=company, module="recruitment", section=tab
            )
    return user


def leave(client, worker, *keep):
    return client.post(
        reverse("access_person", args=[worker.pk]),
        {"action": "companies", "company": list(keep), "paid_by": keep[0]},
    )


def test_removing_member_deletes_their_grants_in_that_company_only(
    client, admin, worker
):
    client.force_login(admin)
    leave(client, worker, "senken")
    assert set(worker.access_grants.values_list("company__slug", flat=True)) == {
        "senken"
    }
    assert worker.access_grants.count() == 2


def test_removal_writes_membership_removed_rows_with_office_admin_as_actor(
    client, admin, worker, avris
):
    client.force_login(admin)
    leave(client, worker, "senken")
    rows = AccessLog.objects.filter(action="membership_removed")
    assert rows.count() == 2
    assert {r.actor for r in rows} == {admin}
    assert {r.company for r in rows} == {avris}
    assert {r.section for r in rows} == {"calling", "sourcing"}


def test_removing_member_also_removes_manager_row(client, admin, worker, avris):
    AccessManager.objects.create(user=worker, company=avris)
    client.force_login(admin)
    leave(client, worker, "senken")
    assert not AccessManager.objects.exists()
    assert AccessLog.objects.filter(action="manager_remove").count() == 1


def test_keeping_every_company_changes_no_grants(client, admin, worker):
    client.force_login(admin)
    leave(client, worker, "senken", "avris")
    assert worker.access_grants.count() == 4
    assert not AccessLog.objects.exists()


def test_office_admin_post_with_grant_field_changes_nothing(client, admin, worker):
    client.force_login(admin)
    client.post(
        reverse("access_person", args=[worker.pk]),
        {"action": "access", "grant": ["recruitment:people:senken"]},
    )
    assert worker.access_grants.count() == 4
    assert not AccessLog.objects.exists()


def test_person_page_has_no_grant_checkboxes(client, admin, worker):
    client.force_login(admin)
    html = client.get(reverse("access_person", args=[worker.pk])).content.decode()
    assert 'name="grant"' not in html
