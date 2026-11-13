from datetime import date, time

import pytest
from django.urls import reverse
from django.utils import timezone

from plans.models import DailyPlan, PlanItem
from plans.services import (
    PANEL_HOUR_HEIGHT,
    PlanError,
    day_panel,
    has_plan_today,
    is_plan_day,
    plan_for,
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
            (None, W, "Early", False, time(8), time(9)),
            (None, W, "Call", False, time(11), time(12)),
        ],
    )
    panel = day_panel(alice, DAY)
    draft, call = panel["blocks"]  # "Early" is before 10:00, so it is left off
    block = draft
    assert block["title"] == "Draft"
    assert block["top"] == 0  # the panel starts at 10:00, so this is cut
    assert block["height"] == PANEL_HOUR_HEIGHT
    assert call["top"] == PANEL_HOUR_HEIGHT and call["height"] == PANEL_HOUR_HEIGHT
    assert [hour.hour for hour, _ in panel["hours"]] == list(range(10, 19))


def test_panel_joins_back_to_back_blocks_of_one_thing(alice):
    save_plan(
        alice,
        DAY,
        [
            (None, G, "Ship it", False, None, None),
            (None, W, "Calls", False, time(10), time(11)),
            (None, W, "Calls", False, time(11), time(12)),
            (None, W, "Calls", False, time(13), time(14)),  # a gap: stays apart
            (None, W, "Review", False, time(12), time(13)),  # other title: apart
        ],
    )
    blocks = day_panel(alice, DAY)["blocks"]
    assert [(b["title"], b["start"], b["end"]) for b in blocks] == [
        ("Calls", time(10), time(12)),
        ("Review", time(12), time(13)),
        ("Calls", time(13), time(14)),
    ]


def test_overlapping_blocks_get_side_by_side_lanes():
    from plans.services import _lanes

    def block(start, end):
        return {"start": time(start), "end": time(end)}

    draft, email, later = _lanes([block(10, 12), block(11, 12), block(14, 15)])
    assert (draft["lane"], draft["lanes"]) == (0, 2)
    assert (email["lane"], email["lanes"]) == (1, 2)
    assert (later["lane"], later["lanes"]) == (0, 1)


def _today_plan(alice):
    from django.utils import timezone

    today = timezone.localdate()
    save_plan(alice, today, [(None, G, "Ship it", False, None, None)])
    return today


def test_add_move_rename_delete_a_block(alice):
    from plans.services import add_block, delete_blocks, move_blocks, rename_blocks

    today = _today_plan(alice)
    add_block(alice, today, "  Calls ", time(10, 15))
    item = alice_items(alice, today)[0]
    assert (item.text, item.starts_at, item.ends_at) == (
        "Calls",
        time(10, 15),
        time(10, 30),
    )
    move_blocks(alice, today, [item.pk], 45)
    item.refresh_from_db()
    assert (item.starts_at, item.ends_at) == (time(11, 0), time(11, 15))
    rename_blocks(alice, today, [item.pk], "Interviews")
    item.refresh_from_db()
    assert item.text == "Interviews"
    delete_blocks(alice, today, [item.pk])
    assert alice_items(alice, today) == []


def alice_items(alice, today):
    return list(plan_for(alice, today).items.filter(kind=W))


def test_blocks_cannot_overlap_leave_the_day_or_be_nameless(alice):
    from plans.services import add_block, move_blocks

    today = _today_plan(alice)
    add_block(alice, today, "A", time(10, 0))
    with pytest.raises(PlanError):
        add_block(alice, today, "B", time(10, 0))
    add_block(alice, today, "B", time(10, 15))  # back to back is fine
    a, b = alice_items(alice, today)
    with pytest.raises(PlanError):
        move_blocks(alice, today, [b.pk], -15)
    with pytest.raises(PlanError):
        move_blocks(alice, today, [a.pk], -11 * 60)
    with pytest.raises(PlanError):
        add_block(alice, today, "  ", time(12, 0))


def test_moving_a_joined_run_moves_every_piece(alice):
    from plans.services import add_block, move_blocks

    today = _today_plan(alice)
    add_block(alice, today, "Calls", time(10, 0))
    add_block(alice, today, "Calls", time(10, 15))
    (block,) = day_panel(alice, today)["blocks"]
    assert len(block["ids"]) == 2 and block["end"] == time(10, 30)
    move_blocks(alice, today, block["ids"], 60)
    (moved,) = day_panel(alice, today)["blocks"]
    assert moved["start"] == time(11, 0) and moved["end"] == time(11, 30)


def test_block_endpoint_is_only_for_your_own_plan(client, alice, django_user_model):
    today = _today_plan(alice)
    client.force_login(alice)
    ok = client.post(
        reverse("plans:block"), {"action": "add", "start": "10:00", "title": "Calls"}
    )
    assert ok.status_code == 200
    bad = client.post(
        reverse("plans:block"), {"action": "add", "start": "10:00", "title": "Again"}
    )
    assert bad.status_code == 400 and "overlaps" in bad.json()["error"]
    item = alice_items(alice, today)[0]
    other = django_user_model.objects.create_user("bob2", password="x")
    client.force_login(other)
    stolen = client.post(reverse("plans:block"), {"action": "delete", "ids": item.pk})
    assert stolen.status_code == 400 and alice_items(alice, today)
    assert client.get(reverse("plans:panel")).status_code == 200


def test_goal_endpoint_sets_done_and_guards_ownership(client, alice, django_user_model):
    plan = DailyPlan.objects.get(user=alice, date=_today_plan(alice))
    goal = plan.items.get(kind=PlanItem.Kind.GOAL)
    work = PlanItem.objects.create(plan=plan, kind=PlanItem.Kind.WORK, text="Calls")
    url = reverse("plans:block")
    client.force_login(alice)
    for _ in range(2):  # repeating the same click leaves it done
        assert (
            client.post(
                url, {"action": "toggle_goal", "id": goal.pk, "done": "1"}
            ).status_code
            == 200
        )
        goal.refresh_from_db()
        assert goal.done
    client.post(url, {"action": "toggle_goal", "id": goal.pk, "done": "0"})
    goal.refresh_from_db()
    assert not goal.done
    for bad in ({"id": work.pk}, {"id": "x"}, {}):
        r = client.post(url, {"action": "toggle_goal", "done": "1", **bad})
        assert r.status_code == 400 and "goal is gone" in r.json()["error"]
    client.force_login(django_user_model.objects.create_user("bob3", password="x"))
    r = client.post(url, {"action": "toggle_goal", "id": goal.pk, "done": "1"})
    goal.refresh_from_db()
    assert r.status_code == 400 and not goal.done
