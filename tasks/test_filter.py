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
