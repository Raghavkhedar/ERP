from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .models import Status, Task
from .services import assign, set_status
from .timeline import DAYS, DAYS_BEFORE_TODAY, build, parse_start

pytestmark = pytest.mark.django_db

TIMELINE_URL = reverse("tasks:timeline")


@pytest.fixture
def today():
    return timezone.localdate()


def make(boss, person, received_days_ago, due_in, description="Audit report"):
    today = timezone.localdate()
    task = assign(boss, person, 3, description, today + timedelta(days=max(due_in, 0)))
    Task.objects.filter(pk=task.pk).update(
        received_at=timezone.now() - timedelta(days=received_days_ago),
        due_date=today + timedelta(days=due_in),
    )
    return Task.objects.get(pk=task.pk)


def bars(timeline):
    return [bar for group in timeline.groups for bar in group.bars]


def test_the_window_starts_a_few_days_back(alice, today):
    timeline = build(alice)

    assert timeline.start == today - timedelta(days=DAYS_BEFORE_TODAY)
    assert len(timeline.days) == DAYS
    assert timeline.today_column == DAYS_BEFORE_TODAY + 2


def test_a_bar_runs_from_received_to_completion_date(boss, alice):
    make(boss, alice, received_days_ago=1, due_in=3)

    [bar] = bars(build(alice))

    assert bar.start == DAYS_BEFORE_TODAY - 1 + 2
    assert bar.end == DAYS_BEFORE_TODAY + 3 + 3
    assert bar.shows_due
    assert not (bar.clipped_left or bar.clipped_right or bar.overdue_from)


def test_bars_are_clipped_at_the_window_edges(boss, alice):
    make(boss, alice, received_days_ago=30, due_in=30)

    [bar] = bars(build(alice))

    assert (bar.start, bar.end) == (2, DAYS + 2)
    assert bar.clipped_left and bar.clipped_right
    assert not bar.shows_due


def test_an_overdue_task_runs_red_to_today(boss, alice):
    make(boss, alice, received_days_ago=3, due_in=-2)

    [bar] = bars(build(alice))

    assert bar.overdue_from == DAYS_BEFORE_TODAY - 1 + 2
    assert bar.end == DAYS_BEFORE_TODAY + 3


def test_tasks_outside_the_window_are_left_out(boss, alice, today):
    make(boss, alice, received_days_ago=1, due_in=3)

    assert bars(build(alice, today + timedelta(days=30))) == []
    assert bars(build(alice, today - timedelta(days=60))) == []


@pytest.mark.parametrize("status", [Status.DONE, Status.CLOSED])
def test_finished_tasks_leave_the_timeline(boss, alice, status):
    task = make(boss, alice, received_days_ago=1, due_in=3)
    assert len(bars(build(alice))) == 1

    set_status(task, boss, status)

    assert bars(build(alice)) == []


def test_employees_see_their_own_tasks(boss, alice, bob):
    mine = make(boss, alice, 1, 3)
    make(boss, bob, 1, 3)

    timeline = build(alice)

    assert [group.person for group in timeline.groups] == [None]
    assert [bar.task for bar in bars(timeline)] == [mine]


def test_assigners_see_everyone_grouped_by_person(boss, alice, bob):
    make(boss, alice, 1, 3)
    make(boss, bob, 1, 3)
    make(boss, alice, 1, 3, "Second")

    timeline = build(boss)

    assert [group.person for group in timeline.groups] == [alice, bob]
    assert len(timeline.groups[0].bars) == 2


def test_from_moves_the_window(today):
    assert parse_start("2026-01-05", today).isoformat() == "2026-01-05"
    assert parse_start("nonsense", today) == today - timedelta(days=DAYS_BEFORE_TODAY)


def test_the_home_page_shows_the_timeline(client, boss, alice):
    make(boss, alice, 1, 3, "Audit report for Q3")
    client.force_login(alice)

    response = client.get(reverse("home"))

    assert b"Audit report for Q3" in response.content
    assert b"Add task" not in response.content


def test_assigners_get_add_task_on_the_home_page(client, boss):
    client.force_login(boss)

    response = client.get(reverse("home"))

    assert b"Add task" in response.content
    assert b"No open tasks" in response.content


def test_the_week_arrows_load_the_timeline_alone(client, alice, today):
    client.force_login(alice)
    start = today + timedelta(days=7)

    response = client.get(TIMELINE_URL, {"from": start.isoformat()})

    assert b"<html" not in response.content
    assert response.context["timeline"].start == start
