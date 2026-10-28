import pytest


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
def boss(django_user_model):
    return django_user_model.objects.create_user(
        username="boss", first_name="boss", password="pw", is_superuser=True
    )
