import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="caller", password="test-pass-123"
    )


def test_admin_login_page_loads(client):
    response = client.get(reverse("admin:login"))
    assert response.status_code == 200


def test_home_redirects_anonymous_to_login(client):
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert response.url == f"{reverse('login')}?next={reverse('home')}"


def test_login_page_loads(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200


def test_login_with_valid_credentials_redirects_home(client, user):
    response = client.post(
        reverse("login"), {"username": "caller", "password": "test-pass-123"}
    )
    assert response.status_code == 302
    assert response.url == reverse("home")


def test_login_with_wrong_password_stays_on_login(client, user):
    response = client.post(
        reverse("login"), {"username": "caller", "password": "wrong"}
    )
    assert response.status_code == 200


def test_home_shows_username_when_logged_in(client, user):
    client.force_login(user)
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert "caller" in response.content.decode()


def test_logout_rejects_get(client, user):
    client.force_login(user)
    response = client.get(reverse("logout"))
    assert response.status_code == 405


def test_logout_logs_the_user_out(client, user):
    client.force_login(user)
    response = client.post(reverse("logout"))
    assert response.status_code == 302
    assert response.url == reverse("login")
    assert client.get(reverse("home")).status_code == 302


def test_base_layout_links_frontend_assets(client):
    html = client.get(reverse("login")).content.decode()
    assert "css/app.css" in html
    assert "vendor/htmx.min.js" in html
    assert "vendor/alpine.min.js" in html