import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PROFILE = reverse("profile")


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="S800",
        first_name="Ana",
        last_name="Rao",
        email="ana@example.com",
        password="old-pass-123",
    )


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def details(**overrides):
    data = {
        "action": "profile",
        "first_name": "Ana",
        "last_name": "Rao",
        "email": "ana@example.com",
    }
    return {**data, **overrides}


def test_login_required(client):
    response = client.get(PROFILE)
    assert response.status_code == 302 and response.url.startswith("/login/")


def test_page_shows_the_users_details(logged_in):
    body = logged_in.get(PROFILE).content.decode()
    assert "S800" in body and "ana@example.com" in body


def test_form_is_prefilled_and_shows_employee_id(logged_in):
    body = logged_in.get(PROFILE).content.decode()
    assert 'value="Ana"' in body and 'value="Rao"' in body
    assert 'value="S800"' in body


def test_saving_shows_a_tick(logged_in):
    response = logged_in.post(PROFILE, details(first_name="Anita"), follow=True)
    assert "Details saved" in response.content.decode()
    assert "Details saved" not in logged_in.get(PROFILE).content.decode()


def test_name_change_saves(logged_in, user):
    response = logged_in.post(PROFILE, details(first_name="Anita", last_name="Iyer"))
    assert response.status_code == 302
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("Anita", "Iyer")


def test_first_name_is_required(logged_in, user):
    response = logged_in.post(PROFILE, details(first_name=""))
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "Ana"


def test_email_change_needs_the_current_password(logged_in, user):
    for password in ("", "wrong"):
        response = logged_in.post(
            PROFILE, details(email="new@example.com", current_password=password)
        )
        assert response.status_code == 200
    user.refresh_from_db()
    assert user.email == "ana@example.com"


def test_email_change_with_password_saves(logged_in, user):
    response = logged_in.post(
        PROFILE, details(email="new@example.com", current_password="old-pass-123")
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.email == "new@example.com"


def test_taken_email_is_refused(logged_in, user, django_user_model):
    django_user_model.objects.create_user(
        username="S801", first_name="Bo", email="bo@example.com", password="x-pass-123"
    )
    response = logged_in.post(
        PROFILE, details(email="bo@example.com", current_password="old-pass-123")
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.email == "ana@example.com"


def test_password_change_keeps_the_session(logged_in, user):
    data = {
        "action": "password",
        "old_password": "old-pass-123",
        "new_password1": "brand-new-pass-456",
        "new_password2": "brand-new-pass-456",
    }
    assert logged_in.post(PROFILE, data).status_code == 302
    user.refresh_from_db()
    assert user.check_password("brand-new-pass-456")
    assert logged_in.get(PROFILE).status_code == 200


def test_wrong_old_password_refused(logged_in, user):
    data = {
        "action": "password",
        "old_password": "nope",
        "new_password1": "brand-new-pass-456",
        "new_password2": "brand-new-pass-456",
    }
    assert logged_in.post(PROFILE, data).status_code == 200
    user.refresh_from_db()
    assert user.check_password("old-pass-123")


def test_same_password_refused(logged_in):
    data = {
        "action": "password",
        "old_password": "old-pass-123",
        "new_password1": "old-pass-123",
        "new_password2": "old-pass-123",
    }
    assert logged_in.post(PROFILE, data).status_code == 200


@pytest.mark.real_password_default
def test_forced_change_blocks_profile(client, django_user_model):
    newcomer = django_user_model.objects.create_user(
        username="S802", first_name="Nina", password="temp-pass-123"
    )
    client.force_login(newcomer)
    response = client.get(PROFILE)
    assert response.status_code == 302 and response.url == reverse("password_change")
