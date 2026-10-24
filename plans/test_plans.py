from datetime import date, time

import pytest
from django.urls import reverse
from django.utils import timezone

from plans.models import DailyPlan, PlanItem
from plans.services import (
    PlanError,
    day_panel,
    has_plan_today,
    is_plan_day,
    save_plan,
)

pytestmark = pytest.mark.django_db

T1, T2 = time(9), time(10)
DAY = date(2026, 10, 26)  # a Monday
G, W = PlanItem.Kind.GOAL, PlanItem.Kind.WORK


def test_save_needs_a_goal(alice):
    with pytest.raises(PlanError, match="at least one goal"):
        save_plan(alice, DAY, [(None, W, "call suppliers", False, T1, T2)])
    assert not DailyPlan.objects.exists()


def test_blank_lines_are_ignored(alice):
    save_plan(
        alice,
        DAY,
        [(None, G, "Ship it", False, None, None), (None, W, "   ", False, T1, T2)],
    )
    assert PlanItem.objects.count() == 1


def test_editing_keeps_updates_and_drops_items(alice):
    plan = save_plan(
        alice,
        DAY,
        [(None, G, "Ship it", False, None, None), (None, W, "Draft", False, T1, T2)],
    )
    goal, work = plan.items.all()
    save_plan(
        alice,
        DAY,
        [
            (goal.pk, G, "Ship it today", True, None, None),
            (None, W, "New", False, T1, T2),
        ],
    )
    goal.refresh_from_db()
    assert (goal.text, goal.done) == ("Ship it today", True)
    assert not PlanItem.objects.filter(pk=work.pk).exists()
    assert DailyPlan.objects.count() == 1
    assert plan.items.count() == 2


def test_cannot_touch_another_plans_item(alice, django_user_model):
    bob = django_user_model.objects.create_user(username="bob", password="pw")
    theirs = save_plan(
        bob, DAY, [(None, G, "Bob's goal", False, None, None)]
    ).items.get()
    mine = save_plan(alice, DAY, [(theirs.pk, G, "hijack", False, None, None)])
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
            "start_1": "09:00",
            "end_1": "10:30",
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
    save_plan(alice, timezone.localdate(), [(None, G, "Ship it", False, None, None)])
    client.force_login(alice)
    body = client.get(reverse("home")).content.decode()
    assert "Ship it" in body and "0 of 1 done" in body


def test_work_needs_a_time_slot(alice):
    with pytest.raises(PlanError, match="start and end time"):
        save_plan(
            alice,
            DAY,
            [
                (None, G, "Ship it", False, None, None),
                (None, W, "Draft", False, None, None),
            ],
        )


def test_slot_must_end_after_it_starts(alice):
    with pytest.raises(PlanError, match="end after it starts"):
        save_plan(
            alice,
            DAY,
            [
                (None, G, "Ship it", False, None, None),
                (None, W, "Draft", False, T2, T1),
            ],
        )


def test_slots_cannot_overlap(alice):
    with pytest.raises(PlanError, match="overlap"):
        save_plan(
            alice,
            DAY,
            [
                (None, G, "Ship it", False, None, None),
                (None, W, "Draft", False, time(9), time(11)),
                (None, W, "Call", False, time(10), time(12)),
            ],
        )


def test_back_to_back_slots_are_fine(alice):
    save_plan(
        alice,
        DAY,
        [
            (None, G, "Ship it", False, None, None),
            (None, W, "Draft", False, time(9), time(10)),
            (None, W, "Call", False, time(10), time(11)),
        ],
    )
    assert PlanItem.objects.filter(kind=W).count() == 2


def test_panel_places_work_by_time(alice):
    save_plan(
        alice,
        DAY,
        [
            (None, G, "Ship it", False, None, None),
            (None, W, "Draft", False, time(9), time(11)),
        ],
    )
    panel = day_panel(alice, DAY)
    (block,) = panel["blocks"]
    assert block["title"] == "Draft"
    assert block["top"] == 0  # the panel starts at 09:00
    assert block["height"] == 80
