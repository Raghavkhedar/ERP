import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def employee(django_user_model):
    return django_user_model.objects.create_user(
        username="S123", first_name="Asha", password="test-pass-123"
    )


def test_login_page_has_no_top_bar(client):
    html = client.get(reverse("login")).content.decode()
    assert "<header" not in html
    assert 'name="username"' in html
    assert 'name="password"' in html


def test_wrong_password_shows_clear_error_and_keeps_the_id(client, employee):
    response = client.post(reverse("login"), {"username": "S123", "password": "wrong"})
    html = response.content.decode()
    assert "That employee ID and password don&#x27;t match" in html
    assert "case-sensitive" not in html
    assert 'value="S123"' in html


def test_lowercase_employee_id_logs_in(client, employee):
    response = client.post(
        reverse("login"), {"username": "s123", "password": "test-pass-123"}
    )
    assert response.status_code == 302
    assert response.url == reverse("home")


def test_login_returns_to_next_page(client, employee):
    meetings = reverse("meetings:schedule")
    html = client.get(reverse("login"), {"next": meetings}).content.decode()
    assert f'name="next" value="{meetings}"' in html

    response = client.post(
        reverse("login"),
        {"username": "S123", "password": "test-pass-123", "next": meetings},
    )
    assert response.url == meetings


def test_password_gets_focus_after_a_failed_login(client, employee):
    html = client.get(reverse("login")).content.decode()
    assert 'id="id_username" required autofocus' in html

    response = client.post(reverse("login"), {"username": "S123", "password": "wrong"})
    html = response.content.decode()
    assert 'id="id_password" required autofocus' in html
    assert 'id="id_username" required autofocus' not in html
