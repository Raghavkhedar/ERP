import pytest


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice", first_name="alice", password="pw"
    )
