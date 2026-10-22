import pytest
from django.urls import reverse

from .models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def priya(django_user_model):
    return django_user_model.objects.create_user(
        username=" emp042 ", first_name="Priya", last_name="Sharma", password="pw"
    )


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_superuser(username="boss", password="pw")


def test_employee_id_is_stored_trimmed_in_capitals(priya):
    assert priya.username == "EMP042"


@pytest.mark.parametrize("typed", ["EMP042", "emp042", " Emp042 "])
def test_login_ignores_case_and_spaces(client, priya, typed):
    response = client.post(reverse("login"), {"username": typed, "password": "pw"})
    assert response.status_code == 302


def test_login_page_asks_for_employee_id(client):
    assert "Employee ID" in client.get(reverse("login")).content.decode()


def test_people_are_shown_by_full_name(priya):
    assert priya.display_name == "Priya Sharma"


def test_without_a_name_the_employee_id_is_shown(django_user_model):
    user = django_user_model.objects.create_user(username="emp7")
    assert user.display_name == "EMP7"


def _add_user(client, **data):
    return client.post(
        reverse("admin:core_user_add"),
        {
            "usable_password": "true",
            "password1": "Xq7!vR2#mL",
            "password2": "Xq7!vR2#mL",
        }
        | data,
    )


def test_admin_adds_a_user_with_employee_id_and_name(client, boss):
    client.force_login(boss)
    _add_user(client, username="emp100", first_name="Ravi", last_name="Kumar")

    user = User.objects.get(username="EMP100")
    assert user.display_name == "Ravi Kumar"


def test_admin_cannot_add_a_user_without_a_name(client, boss):
    client.force_login(boss)
    response = _add_user(client, username="emp100")

    assert response.status_code == 200
    assert not User.objects.filter(username="EMP100").exists()


def test_employee_id_differing_only_in_case_is_taken(client, boss, priya):
    client.force_login(boss)
    response = _add_user(client, username="Emp042", first_name="Someone")

    assert response.status_code == 200
    assert User.objects.filter(username="EMP042").count() == 1
