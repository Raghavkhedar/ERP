from datetime import date

import pytest
from django.urls import reverse

from plans.models import PlanItem
from plans.services import can_view, save_plan
from tasks.models import Task

pytestmark = pytest.mark.django_db

DAY = date(2026, 10, 26)


def url(owner):
    return reverse("plans:view", args=[owner.pk, DAY.year, DAY.month, DAY.day])


@pytest.fixture
def assigned(alice, bob):
    """Bob gave Alice a task."""
    Task.objects.create(
        assigned_to=alice,
        assigned_by=bob,
        description="x",
        priority=1,
        due_date=DAY,
    )


def test_owner_sees_own_plan(client, alice):
    save_plan(alice, DAY, [(None, PlanItem.Kind.GOAL, "Ship it", False, None, None)])
    client.force_login(alice)
    assert "Ship it" in client.get(url(alice)).content.decode()


def test_assigner_can_view_but_not_the_reverse(alice, bob, assigned):
    assert can_view(bob, alice)
    assert not can_view(alice, bob)


def test_stranger_is_refused(client, alice, bob):
    client.force_login(bob)
    assert client.get(url(alice)).status_code == 403


def test_superuser_can_view(client, alice, django_user_model):
    boss = django_user_model.objects.create_superuser(username="boss", password="pw")
    client.force_login(boss)
    assert client.get(url(alice)).status_code == 200


def test_assigner_sees_it_in_the_page(client, alice, bob, assigned):
    save_plan(alice, DAY, [(None, PlanItem.Kind.GOAL, "Ship it", False, None, None)])
    client.force_login(bob)
    assert "Ship it" in client.get(url(alice)).content.decode()
