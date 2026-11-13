import pytest
from django.urls import reverse

from .services import assign

pytestmark = pytest.mark.django_db

HOME_URL = reverse("home")
LIST_URL = reverse("tasks:list")
TIMELINE_URL = reverse("tasks:timeline")


@pytest.fixture
def two_tasks(boss, alice, bob, next_week):
    return (
        assign(boss, alice, 1, "Alice's job", next_week),
        assign(boss, bob, 2, "Bob's job", next_week),
    )


def shown(response):
    timeline = response.context["timeline"]
    return [bar.task.title for group in timeline.groups for bar in group.bars]


def test_admins_see_everyone_by_default(client, boss, two_tasks):
    client.force_login(boss)

    response = client.get(HOME_URL)

    assert shown(response) == ["Alice's job", "Bob's job"]
    assert b'id="person-filter"' in response.content


def test_picking_a_person_narrows_the_timeline(client, boss, alice, two_tasks):
    client.force_login(boss)

    response = client.get(TIMELINE_URL, {"person": alice.pk})

    assert shown(response) == ["Alice's job"]
    assert response.context["person"] == alice


def test_the_choice_is_remembered(client, boss, bob, two_tasks):
    client.force_login(boss)
    client.get(TIMELINE_URL, {"person": bob.pk})

    assert shown(client.get(HOME_URL)) == ["Bob's job"]
    assert [t.title for t in client.get(LIST_URL).context["tasks"]] == ["Bob's job"]


def test_everyone_clears_it(client, boss, bob, two_tasks):
    client.force_login(boss)
    client.get(TIMELINE_URL, {"person": bob.pk})

    response = client.get(TIMELINE_URL, {"person": ""})

    assert shown(response) == ["Alice's job", "Bob's job"]


def test_nonsense_means_everyone(client, boss, two_tasks):
    client.force_login(boss)

    response = client.get(LIST_URL, {"person": "abc"})

    assert len(response.context["tasks"]) == 2


def test_employees_get_no_filter_and_cannot_peek(client, alice, bob, two_tasks):
    client.force_login(alice)

    response = client.get(HOME_URL, {"person": bob.pk})

    assert shown(response) == ["Alice's job"]
    assert b'id="person-filter"' not in response.content


def test_filtered_empty_state_names_the_person(client, boss, manager, two_tasks):
    client.force_login(boss)

    response = client.get(LIST_URL, {"person": manager.pk})

    assert b"manager has no open tasks." in response.content


def test_status_filter_narrows_the_task_list(client, boss, alice, next_week):
    from .models import Status

    done = assign(boss, alice, 1, "Finished job", next_week)
    done.status = Status.ONGOING
    done.save()
    assign(boss, alice, 2, "Fresh job", next_week)
    client.force_login(boss)

    titles = lambda r: [t.title for t in r.context["tasks"]]  # noqa: E731

    assert titles(client.get(LIST_URL, {"status": "open"})) == ["Fresh job"]
    assert titles(client.get(LIST_URL, {"status": "ongoing"})) == ["Finished job"]
    assert len(titles(client.get(LIST_URL))) == 2


def test_closed_status_opens_the_closed_section(client, boss, alice, next_week):
    from django.utils import timezone

    from .models import Status

    task = assign(boss, alice, 1, "Old job", next_week)
    task.status = Status.CLOSED
    task.closed_at = timezone.now()
    task.save()
    client.force_login(boss)

    html = client.get(LIST_URL, {"status": "closed"}).content.decode()

    assert "Closed tasks are listed below." in html
    assert '<details class="group mt-10" open>' in html
    assert "Old job" in html
