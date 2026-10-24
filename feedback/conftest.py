import pytest
from django.contrib.auth.models import Group


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


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
def manager(django_user_model):
    user = django_user_model.objects.create_user(
        username="manager", first_name="manager", password="pw"
    )
    user.groups.add(Group.objects.get(name="Office admin"))
    return user


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_user(
        username="boss", first_name="boss", password="pw", is_superuser=True
    )
