import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from .models import Status
from .services import (
    allowed_statuses,
    assign,
    can_assign,
    can_update,
    set_status,
    updatable_tasks,
    visible_tasks,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def lead(django_user_model, alice):
    user = django_user_model.objects.create_user(
        username="lead", first_name="lead", password="pw"
    )
    alice.supervisor = user
    alice.save()
    return user


def test_a_supervisor_assigns_to_their_reports(lead, alice, next_week):
    task = assign(lead, alice, 2, "Reconcile ledger", next_week)

    assert task.assigned_to == alice
    assert can_assign(lead)


def test_a_supervisor_cannot_assign_to_others(lead, bob, next_week):
    with pytest.raises(PermissionDenied):
        assign(lead, bob, 2, "Reconcile ledger", next_week)


def test_someone_without_reports_cannot_assign(alice, bob, next_week):
    assert not can_assign(alice)
    with pytest.raises(PermissionDenied):
        assign(alice, bob, 2, "Reconcile ledger", next_week)


def test_a_supervisor_sees_reports_and_own_tasks_only(
    lead, alice, bob, boss, next_week
):
    theirs = assign(boss, alice, 1, "Audit", next_week)
    own = assign(boss, lead, 1, "Budget", next_week)
    assign(boss, bob, 1, "Vendor KYC", next_week)

    assert set(visible_tasks(lead)) == {theirs, own}


def test_a_supervisor_manages_a_reports_task(lead, alice, boss, next_week):
    task = assign(boss, alice, 1, "Audit", next_week)

    assert allowed_statuses(task, lead) == list(Status)
    assert can_update(task, lead)
    assert task in updatable_tasks(lead)
    set_status(task, lead, Status.DONE)
    assert task in updatable_tasks(lead)  # a supervisor can still log on done


def test_a_supervisor_does_not_manage_their_own_task(lead, boss, next_week):
    task = assign(boss, lead, 1, "Budget", next_week)

    assert allowed_statuses(task, lead) == []


def test_the_assign_form_lists_only_reports_and_self(client, lead, alice, bob):
    client.force_login(lead)

    response = client.get(reverse("tasks:new"))

    people = set(response.context["form"].fields["assigned_to"].queryset)
    assert people == {lead, alice}


def test_a_supervisor_edits_a_reports_task_but_not_others(
    client, lead, alice, bob, boss, next_week
):
    theirs = assign(boss, alice, 1, "Audit", next_week)
    other = assign(boss, bob, 1, "Vendor KYC", next_week)
    client.force_login(lead)

    assert client.get(reverse("tasks:edit", args=[theirs.pk])).status_code == 200
    assert client.get(reverse("tasks:edit", args=[other.pk])).status_code == 404
