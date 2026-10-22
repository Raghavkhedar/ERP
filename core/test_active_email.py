import pytest
from django.db import IntegrityError
from django.urls import reverse

from .models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def old_intern(django_user_model):
    return django_user_model.objects.create_user(
        username="S010", first_name="Asha", email="intern@senken.example"
    )


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_superuser(username="boss", password="pw")


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


def test_deactivating_someone_clears_their_email(old_intern):
    old_intern.is_active = False
    old_intern.save()

    old_intern.refresh_from_db()
    assert old_intern.email == ""


def test_deactivating_with_update_fields_also_clears_the_email(old_intern):
    old_intern.is_active = False
    old_intern.save(update_fields=["is_active"])

    old_intern.refresh_from_db()
    assert old_intern.email == ""


def test_history_still_shows_the_old_email(old_intern):
    old_intern.is_active = False
    old_intern.save()

    assert [h.email for h in old_intern.history.order_by("history_id")] == [
        "intern@senken.example",
        "",
    ]


def test_database_refuses_two_active_accounts_with_one_email(
    old_intern, django_user_model
):
    with pytest.raises(IntegrityError):
        django_user_model.objects.create_user(
            username="S011", email="INTERN@senken.example"
        )


def test_many_accounts_may_have_no_email(django_user_model):
    django_user_model.objects.create_user(username="S1")
    django_user_model.objects.create_user(username="S2")


def test_admin_refuses_an_email_an_active_account_holds(client, boss, old_intern):
    client.force_login(boss)
    response = _add_user(
        client, username="s011", first_name="Ravi", email="Intern@senken.example"
    )

    assert response.status_code == 200
    assert "Asha (S010) still has this email" in response.content.decode()
    assert not User.objects.filter(username="S011").exists()


def test_new_intern_gets_a_fresh_account_after_the_old_one_is_deactivated(
    client, boss, old_intern
):
    old_intern.is_active = False
    old_intern.save()
    client.force_login(boss)

    _add_user(client, username="s011", first_name="Ravi", email="intern@senken.example")

    new_intern = User.objects.get(username="S011")
    assert new_intern.email == "intern@senken.example"
    assert new_intern.pk != old_intern.pk


def test_saving_an_account_keeps_its_own_email(client, boss, old_intern):
    client.force_login(boss)
    response = client.post(
        reverse("admin:core_user_change", args=[old_intern.pk]),
        {
            "username": "S010",
            "first_name": "Asha",
            "email": "intern@senken.example",
            "is_active": "on",
            "date_joined_0": "2026-10-22",
            "date_joined_1": "09:00:00",
        },
    )

    assert response.status_code == 302
