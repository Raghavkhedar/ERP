import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from notifications.models import Notification

from .models import Area, Kind, Status
from .services import (
    FeedbackError,
    add_comment,
    assign_to_supervisor,
    submit,
    unassign,
    visible_feedback,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def lead(django_user_model):
    return django_user_model.objects.create_user(
        username="lead", first_name="lead", password="pw"
    )


@pytest.fixture
def item(alice, lead):
    alice.supervisor = lead
    alice.save()
    return submit(alice, Kind.PROBLEM, Area.TASKS, "Broken")


@pytest.fixture
def other_item(bob):
    return submit(bob, Kind.PROBLEM, Area.TASKS, "Also broken")


def test_assign_picks_the_submitters_supervisor_and_notifies(item, boss, lead):
    assign_to_supervisor(item, boss)
    item.refresh_from_db()
    assert item.assigned_to == lead
    note = Notification.objects.get(user=lead)
    assert note.url == reverse("feedback:detail", args=[item.pk])


def test_no_supervisor_is_a_clear_error(other_item, boss):
    with pytest.raises(FeedbackError, match="no supervisor"):
        assign_to_supervisor(other_item, boss)


@pytest.mark.parametrize("who", ["alice", "manager", "trainer", "lead"])
def test_only_superadmins_assign(item, request, who):
    with pytest.raises(PermissionDenied):
        assign_to_supervisor(item, request.getfixturevalue(who))
    with pytest.raises(PermissionDenied):
        unassign(item, request.getfixturevalue(who))


def test_supervisor_sees_only_the_assigned_thread(client, item, other_item, boss, lead):
    assign_to_supervisor(item, boss)
    assert list(visible_feedback(lead)) == [item]
    client.force_login(lead)
    assert client.get(reverse("feedback:detail", args=[item.pk])).status_code == 200
    other = reverse("feedback:detail", args=[other_item.pk])
    assert client.get(other).status_code == 404


def test_supervisor_replies_and_the_submitter_is_told(item, boss, lead, alice):
    assign_to_supervisor(item, boss)
    add_comment(item, lead, "Looking into it.")
    assert Notification.objects.filter(user=alice, text__contains="commented").exists()
    item.refresh_from_db()
    assert item.status == Status.NEW  # only a reader's reply starts the discussion


def test_supervisor_is_told_when_the_submitter_comments(item, boss, lead, alice):
    assign_to_supervisor(item, boss)
    Notification.objects.all().delete()
    add_comment(item, alice, "More detail.")
    assert Notification.objects.filter(user=lead, text__contains="commented").exists()


def test_supervisor_cannot_resolve_or_assign(client, item, boss, lead):
    assign_to_supervisor(item, boss)
    client.force_login(lead)
    resolve = {"status": "resolved", "outcome": "fixed"}
    assert (
        client.post(reverse("feedback:resolve", args=[item.pk]), resolve).status_code
        == 403
    )
    assert client.post(reverse("feedback:assign", args=[item.pk])).status_code == 404
    assert client.post(reverse("feedback:unassign", args=[item.pk])).status_code == 404


def test_superadmin_assigns_and_removes_through_the_pages(client, item, boss, lead):
    client.force_login(boss)
    client.post(reverse("feedback:assign", args=[item.pk]))
    item.refresh_from_db()
    assert item.assigned_to == lead
    client.post(reverse("feedback:unassign", args=[item.pk]))
    item.refresh_from_db()
    assert item.assigned_to is None
    assert list(visible_feedback(lead)) == []


def test_assign_control_is_for_superadmins_only(client, item, manager, boss):
    url = reverse("feedback:assign", args=[item.pk])
    client.force_login(manager)
    assert (
        url
        not in client.get(reverse("feedback:detail", args=[item.pk])).content.decode()
    )
    assert client.post(url).status_code == 404
    client.force_login(boss)
    assert (
        url in client.get(reverse("feedback:detail", args=[item.pk])).content.decode()
    )
