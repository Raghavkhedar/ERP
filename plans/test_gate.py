from datetime import date

import pytest
from django.urls import reverse

from plans.models import PlanItem
from plans.services import save_plan

pytestmark = [pytest.mark.django_db, pytest.mark.real_plan_gate]

MONDAY, SUNDAY = date(2026, 10, 26), date(2026, 10, 25)


@pytest.fixture(autouse=True)
def on_a_monday(monkeypatch):
    monkeypatch.setattr("django.utils.timezone.localdate", lambda *a, **k: MONDAY)


def test_no_plan_sends_you_to_the_plan_page(client, alice):
    client.force_login(alice)
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert response.url == reverse("plans:today")


def test_htmx_gets_a_redirect_header(client, alice):
    client.force_login(alice)
    response = client.get(reverse("tasks:list"), HTTP_HX_REQUEST="true")
    assert response.status_code == 204
    assert response["HX-Redirect"] == reverse("plans:today")


def test_plan_page_and_logout_stay_reachable(client, alice):
    client.force_login(alice)
    assert client.get(reverse("plans:today")).status_code == 200
    assert client.post(reverse("logout")).status_code == 302


def test_saving_a_plan_unlocks_the_app(client, alice):
    client.force_login(alice)
    save_plan(alice, MONDAY, [(None, PlanItem.Kind.GOAL, "Ship it", False, None, None)])
    assert client.get(reverse("home")).status_code == 200


def test_sunday_is_free(client, alice, monkeypatch):
    monkeypatch.setattr("django.utils.timezone.localdate", lambda *a, **k: SUNDAY)
    client.force_login(alice)
    assert client.get(reverse("home")).status_code == 200


@pytest.mark.real_password_default
def test_password_comes_first(client, alice):
    alice.must_change_password = True
    alice.save()
    client.force_login(alice)
    assert client.get(reverse("home")).url == reverse("password_change")
