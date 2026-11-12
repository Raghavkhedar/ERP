import pytest
from django.db import IntegrityError

from core.models import AccessLog, AccessManager, Company

pytestmark = pytest.mark.django_db


@pytest.fixture
def senken():
    return Company.objects.get(slug="senken")


@pytest.fixture
def log(django_user_model, senken):
    actor = django_user_model.objects.create_user(username="boss", password="pw")
    return AccessLog.objects.create(
        actor=actor,
        actor_name="boss",
        subject=actor,
        subject_name="boss",
        company=senken,
        module="recruitment",
        section="calling",
        action=AccessLog.Action.GRANT,
    )


def test_log_row_cannot_be_edited(log):
    log.note = "changed"
    with pytest.raises(PermissionError):
        log.save()


def test_log_row_cannot_be_deleted(log):
    with pytest.raises(PermissionError):
        log.delete()
    with pytest.raises(PermissionError):
        AccessLog.objects.all().delete()
    with pytest.raises(PermissionError):
        AccessLog.objects.all().update(note="x")
    assert AccessLog.objects.count() == 1


def test_log_survives_deleting_actor(log):
    log.actor.delete()
    log.refresh_from_db()
    assert log.actor is None
    assert log.actor_name == "boss"


def test_manager_unique_per_company(django_user_model, senken):
    user = django_user_model.objects.create_user(username="m", password="pw")
    AccessManager.objects.create(user=user, company=senken)
    with pytest.raises(IntegrityError):
        AccessManager.objects.create(user=user, company=senken)
