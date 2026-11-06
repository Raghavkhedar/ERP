import pytest
from django.urls import reverse

from core.models import AccessGrant, Company

from .models import Person
from .widgets import PhoneWidget, split_phone

pytestmark = pytest.mark.django_db


def test_split_phone():
    assert split_phone("+971 50 123 4567") == ("+971", "50 123 4567")
    assert split_phone("+91 98765 43210") == ("+91", "98765 43210")
    assert split_phone("98765 43210") == ("+91", "98765 43210")
    assert split_phone("+49 151 2345678") == ("", "+49 151 2345678")
    assert split_phone(None) == ("+91", "")


def test_widget_joins_code_and_number_and_accepts_plain_post():
    w = PhoneWidget()
    post = {"phone_code": "+44", "phone_number": " 7700 900123 "}
    assert w.value_from_datadict(post, {}, "phone") == "+44 7700 900123"
    assert w.value_from_datadict({"phone": "98765 43210"}, {}, "phone") == "98765 43210"
    assert (
        w.value_from_datadict({"phone_code": "+44", "phone_number": ""}, {}, "phone")
        == ""
    )


def test_candidate_form_saves_with_country_code(client, django_user_model):
    senken = Company.objects.get(slug="senken")
    user = django_user_model.objects.create_user("c1", password="x")
    senken.memberships.create(user=user)
    AccessGrant.objects.create(
        user=user, company=senken, module="recruitment", section="candidates"
    )
    client.force_login(user)
    page = client.get(reverse("people:new"))
    assert b'name="phone_code"' in page.content
    client.post(
        reverse("people:new"),
        {
            "name": "Omar",
            "phone_code": "+971",
            "phone_number": "50 123 4567",
            "contact_status": "active",
        },
    )
    person = Person.objects.get(name="Omar")
    assert person.phone == "+971 50 123 4567"
    assert person.phone_key == "1501234567"
