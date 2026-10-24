import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.real_password_default]

CHANGE = reverse("password_change")


@pytest.fixture
def newcomer(django_user_model):
    """An account an admin just made: must choose a password first."""
    return django_user_model.objects.create_user(
        username="S900", first_name="Nina", password="temp-pass-123"
    )


@pytest.fixture
def veteran(django_user_model):
    user = django_user_model.objects.create_user(
        username="S901", first_name="Vic", password="old-pass-123"
    )
    user.must_change_password = False
    user.save()
    return user


def test_new_accounts_must_change_their_password(newcomer):
    assert newcomer.must_change_password


def test_everything_redirects_to_the_change_page(client, newcomer):
    client.force_login(newcomer)

    for url in ("/", reverse("tasks:list"), reverse("meetings:schedule")):
        response = client.get(url)
        assert response.status_code == 302 and response.url == CHANGE


def test_htmx_requests_are_told_to_redirect(client, newcomer):
    client.force_login(newcomer)

    response = client.get(reverse("tasks:list"), headers={"HX-Request": "true"})

    assert response.status_code == 204
    assert response["HX-Redirect"] == CHANGE


def test_the_change_page_and_logout_stay_reachable(client, newcomer):
    client.force_login(newcomer)

    assert client.get(CHANGE).status_code == 200
    assert client.post(reverse("logout")).status_code == 302


def test_choosing_a_password_lets_them_in_and_keeps_them_logged_in(client, newcomer):
    client.force_login(newcomer)

    response = client.post(
        CHANGE,
        {
            "old_password": "temp-pass-123",
            "new_password1": "a-much-better-pass-77",
            "new_password2": "a-much-better-pass-77",
        },
    )

    assert response.status_code == 302 and response.url == "/"
    newcomer.refresh_from_db()
    assert not newcomer.must_change_password
    assert newcomer.check_password("a-much-better-pass-77")
    assert client.get("/").status_code == 200  # session survived the change


def test_the_same_password_is_refused(client, newcomer):
    client.force_login(newcomer)

    response = client.post(
        CHANGE,
        {
            "old_password": "temp-pass-123",
            "new_password1": "temp-pass-123",
            "new_password2": "temp-pass-123",
        },
    )

    assert response.status_code == 200
    assert "different from your current one" in response.content.decode()
    newcomer.refresh_from_db()
    assert newcomer.must_change_password


def test_a_wrong_current_password_is_refused(client, newcomer):
    client.force_login(newcomer)

    response = client.post(
        CHANGE,
        {
            "old_password": "nope",
            "new_password1": "a-much-better-pass-77",
            "new_password2": "a-much-better-pass-77",
        },
    )

    assert "your current password. Try again" in response.content.decode()
    newcomer.refresh_from_db()
    assert newcomer.must_change_password


def test_existing_people_are_not_interrupted(client, veteran):
    client.force_login(veteran)
    assert client.get("/").status_code == 200
    assert client.get(CHANGE).status_code == 200  # they may still change it


def test_an_admin_resetting_a_password_forces_a_change(
    client, veteran, django_user_model
):
    boss = django_user_model.objects.create_superuser(
        username="S1", first_name="Boss", password="boss-pass-123"
    )
    boss.must_change_password = False
    boss.save()
    client.force_login(boss)

    client.post(
        reverse("admin:auth_user_password_change", args=[veteran.pk]),
        {
            "usable_password": "true",
            "password1": "reset-pass-4567",
            "password2": "reset-pass-4567",
        },
    )

    veteran.refresh_from_db()
    assert veteran.check_password("reset-pass-4567")
    assert veteran.must_change_password
