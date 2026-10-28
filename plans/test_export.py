from datetime import date, time
from io import BytesIO

import pytest
from django.urls import reverse
from openpyxl import load_workbook

from .services import save_plan

pytestmark = pytest.mark.django_db


def rows(response):
    book = load_workbook(BytesIO(response.content))
    return list(book["Plan"].values)


@pytest.fixture
def plans(alice):
    save_plan(
        alice, date(2026, 10, 1), [(None, "goal", "=Close books", False, None, None)]
    )
    save_plan(
        alice,
        date(2026, 10, 2),
        [
            (None, "goal", "Ship it", True, None, None),
            (None, "work", "Review", False, time(10), time(11)),
        ],
    )


def test_owner_exports_all_their_plans(client, alice, plans):
    client.force_login(alice)
    data = rows(client.get(reverse("plans:export", args=[alice.pk])))
    assert [r[0].date() for r in data[1:]] == [date(2026, 10, 2)] * 2 + [
        date(2026, 10, 1)
    ]
    assert data[-1][3] == "'=Close books"
    assert ("Work", "Review") == data[2][2:4]
    assert (time(10), time(11)) == data[2][5:7]


def test_dates_narrow_the_export(client, alice, plans):
    client.force_login(alice)
    url = reverse("plans:export", args=[alice.pk]) + "?from=2026-10-02&to=2026-10-02"
    assert len(rows(client.get(url))) == 3
    junk = reverse("plans:export", args=[alice.pk]) + "?from=nonsense"
    assert len(rows(client.get(junk))) == 4


def test_a_stranger_is_refused_and_a_superadmin_allowed(
    client, alice, bob, boss, plans
):
    url = reverse("plans:export", args=[alice.pk])
    client.force_login(bob)
    assert client.get(url).status_code == 403
    client.force_login(boss)
    assert client.get(url).status_code == 200
