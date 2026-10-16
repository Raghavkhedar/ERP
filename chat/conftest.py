import pytest


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(username="alice", password="pw")


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(username="bob", password="pw")


@pytest.fixture
def carol(django_user_model):
    return django_user_model.objects.create_user(username="carol", password="pw")
