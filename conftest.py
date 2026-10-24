import pytest


@pytest.fixture(autouse=True)
def accounts_start_ready(request):
    """Test users can use the app at once, without choosing a password first.

    New real accounts must change their password (core.middleware); tests that
    cover that opt out with @pytest.mark.real_password_default.
    """
    if request.node.get_closest_marker("real_password_default"):
        yield
        return
    from core.models import User

    field = User._meta.get_field("must_change_password")
    original = field.default
    field.default = False
    yield
    field.default = original


@pytest.fixture(autouse=True)
def plan_gate_off(request, monkeypatch):
    """Tests can use the app without setting today's plan first.

    Tests that cover the gate opt back in with @pytest.mark.real_plan_gate.
    """
    if not request.node.get_closest_marker("real_plan_gate"):
        monkeypatch.setattr("core.middleware.has_plan_today", lambda user: True)
