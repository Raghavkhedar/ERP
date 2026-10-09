# Create your tests here.
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_admin_login_page_loads(client):
    response = client.get(reverse("admin:login"))
    assert response.status_code == 200