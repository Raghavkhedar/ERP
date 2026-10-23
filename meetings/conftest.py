import pytest

from meetings import views


@pytest.fixture(autouse=True)
def no_office_hours_on_demand(request, monkeypatch):
    """Pages would open office hours for the real today; most tests don't want that."""
    if not request.node.get_closest_marker("office_hours_on_demand"):
        monkeypatch.setattr(views, "open_upcoming_office_hours", lambda: None)


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
