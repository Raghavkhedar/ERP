from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from plans.models import DailyPlan, PlanItem
from plans.services import PlanError, has_plan_today, is_plan_day, save_plan

pytestmark = pytest.mark.django_db

DAY = date(2026, 10, 26)  # a Monday
G, W = PlanItem.Kind.GOAL, PlanItem.Kind.WORK


def test_save_needs_a_goal(alice):
    with pytest.raises(PlanError, match="at least one goal"):
        save_plan(alice, DAY, [(None, W, "call suppliers", False)])
    assert not DailyPlan.objects.exists()


def test_blank_lines_are_ignored(alice):
    save_plan(alice, DAY, [(None, G, "Ship it", False), (None, W, "   ", False)])
    assert PlanItem.objects.count() == 1


def test_editing_keeps_updates_and_drops_items(alice):
    plan = save_plan(
        alice, DAY, [(None, G, "Ship it", False), (None, W, "Draft", False)]
    )
    goal, work = plan.items.all()
    save_plan(
        alice, DAY, [(goal.pk, G, "Ship it today", True), (None, W, "New", False)]
    )
    goal.refresh_from_db()
    assert (goal.text, goal.done) == ("Ship it today", True)
    assert not PlanItem.objects.filter(pk=work.pk).exists()
    assert DailyPlan.objects.count() == 1
    assert plan.items.count() == 2


def test_cannot_touch_another_plans_item(alice, django_user_model):
    bob = django_user_model.objects.create_user(username="bob", password="pw")
    theirs = save_plan(bob, DAY, [(None, G, "Bob's goal", False)]).items.get()
    mine = save_plan(alice, DAY, [(theirs.pk, G, "hijack", False)])
    theirs.refresh_from_db()
    assert theirs.text == "Bob's goal"
    assert mine.items.get().text == "hijack"


def test_plan_days_are_monday_to_saturday():
    assert is_plan_day(date(2026, 10, 24))  # Saturday
    assert not is_plan_day(date(2026, 10, 25))  # Sunday


def test_page_saves_and_unlocks(client, alice):
    client.force_login(alice)
    assert not has_plan_today(alice)
    response = client.post(
        reverse("plans:today"),
        {
            "row": ["0", "1"],
            "kind_0": "goal",
            "text_0": "Ship it",
            "id_0": "",
            "kind_1": "work",
            "text_1": "Draft",
            "done_1": "on",
            "id_1": "",
        },
    )
    assert response.status_code == 302
    assert has_plan_today(alice)
    assert PlanItem.objects.get(text="Draft").done


def test_page_shows_error_without_goal(client, alice):
    client.force_login(alice)
    response = client.post(
        reverse("plans:today"), {"row": ["0"], "kind_0": "work", "text_0": "x"}
    )
    assert response.status_code == 200
    assert "at least one goal" in response.content.decode()


def test_home_shows_the_plan(client, alice, monkeypatch):
    monkeypatch.setattr("core.views.is_plan_day", lambda day: True)
    save_plan(alice, timezone.localdate(), [(None, G, "Ship it", False)])
    client.force_login(alice)
    body = client.get(reverse("home")).content.decode()
    assert "Ship it" in body and "0 of 1 done" in body
