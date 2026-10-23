from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from .services import assign


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_user(
        username="boss", first_name="boss", password="pw", is_superuser=True
    )


@pytest.fixture
def manager(django_user_model):
    user = django_user_model.objects.create_user(
        username="manager", first_name="manager", password="pw"
    )
    user.groups.add(Group.objects.get(name="Office admin"))
    return user


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice", first_name="alice", password="pw"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="bob", first_name="bob", password="pw"
    )


@pytest.fixture
def next_week():
    return timezone.localdate() + timedelta(days=7)


@pytest.fixture
def task(boss, alice, next_week):
    return assign(
        boss, alice, 3, "Audit report for Q3\nWith the bank statements", next_week
    )
