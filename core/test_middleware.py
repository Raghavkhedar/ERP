import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

HTMX = {"HX-Request": "true"}


def test_htmx_request_without_session_reloads_the_page(client):
    response = client.get(reverse("chat:conversation_list"), headers=HTMX)
    assert response.status_code == 204
    assert response["HX-Refresh"] == "true"


def test_plain_request_without_session_still_goes_to_login(client):
    response = client.get(reverse("chat:conversation_list"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))
