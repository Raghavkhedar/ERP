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
def carol(django_user_model):
    return django_user_model.objects.create_user(
        username="carol", first_name="carol", password="pw"
    )
