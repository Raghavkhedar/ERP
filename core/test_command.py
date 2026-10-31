from datetime import date

import pytest
from django.urls import reverse

from core.models import AccessGrant, Company
from people.models import Person
from tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


def labels(client, q=""):
    data = client.get(reverse("command"), {"q": q}).json()["results"]
    return [(r["group"], r["label"]) for r in data]


def test_needs_login(client):
    assert client.get(reverse("command")).status_code == 302


def test_plain_user_sees_only_the_everyday_pages(client, django_user_model):
    user = django_user_model.objects.create_user("plain", password="x")
    client.force_login(user)
    found = labels(client)
    assert ("Pages", "Tasks") in found and ("Pages", "Candidates") not in found
    assert labels(client, "sourc") == []


def test_recruiter_finds_pages_candidates_and_tasks(client, django_user_model, senken):
    user = django_user_model.objects.create_user("rec", password="x")
    senken.memberships.create(user=user)
    AccessGrant.objects.create(
        user=user, company=senken, module="recruitment", section="candidates"
    )
    Person.objects.create(company=senken, name="Ravi Kumar", phone="+91 98765 43210")
    Task.objects.create(
        description="Call Ravi's referee",
        assigned_to=user,
        assigned_by=user,
        priority=1,
        due_date=date(2031, 1, 1),
    )
    client.force_login(user)
    assert ("Pages", "Sourcing") in labels(client, "sourc")
    assert ("Pages", "Preparing") not in labels(client)  # needs Openings
    found = labels(client, "ravi")
    assert ("Candidates", "Ravi Kumar") in found
    assert ("Tasks", "Call Ravi's referee") in found
    assert ("Candidates", "Ravi Kumar") not in labels(client, "r")  # 2+ letters
