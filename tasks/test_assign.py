from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from chat.models import Message
from chat.services import unread_counts

from .models import Status, Task
from .services import TaskError, assign, short_date

pytestmark = pytest.mark.django_db

NEW_URL = reverse("tasks:new")
HTMX = {"HX-Request": "true"}


def form_data(person, **changes):
    data = {
        "assigned_to": person.pk,
        "priority": "3",
        "description": "Audit report",
        "due_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
    }
    return {**data, **changes}


# Service


def test_assigning_a_task(task, boss, alice, next_week):
    assert task.assigned_to == alice
    assert task.assigned_by == boss
    assert task.priority == 3
    assert task.due_date == next_week
    assert task.status == Status.OPEN
    assert task.received_at is not None


def test_the_title_is_the_first_line(task):
    assert task.title == "Audit report for Q3"


def test_assigning_tells_the_assignee_in_their_dm(task, boss, alice, next_week):
    notice = Message.objects.get()
    assert notice.is_notice
    assert notice.author == boss
    assert notice.body == (
        f"assigned you a task (P3, due {short_date(next_week)}): Audit report for Q3"
    )
    assert unread_counts(alice) == {notice.conversation_id: 1}


def test_office_admins_assign_tasks(manager, alice, next_week):
    assign(manager, alice, 1, "Vendor KYC", next_week)

    assert Task.objects.get().assigned_by == manager


def test_employees_cannot_assign(alice, bob, next_week):
    with pytest.raises(PermissionDenied):
        assign(alice, bob, 1, "Vendor KYC", next_week)


def test_a_leaver_cannot_get_a_task(boss, alice, next_week):
    alice.is_active = False
    alice.save()

    with pytest.raises(TaskError):
        assign(boss, alice, 1, "Vendor KYC", next_week)


def test_completion_date_cannot_be_past(boss, alice):
    with pytest.raises(TaskError):
        assign(boss, alice, 1, "Vendor KYC", timezone.localdate() - timedelta(days=1))


# Page


def test_employees_get_the_form_without_a_person_picker(client, alice):
    client.force_login(alice)

    response = client.get(NEW_URL)

    assert response.status_code == 200
    assert b'name="assigned_to"' not in response.content


def test_the_dialog_gets_the_form_alone(client, boss):
    client.force_login(boss)

    response = client.get(NEW_URL, headers=HTMX)

    assert response.status_code == 200
    assert b"<html" not in response.content
    assert b"Received now" in response.content


def test_without_javascript_the_form_is_a_page(client, boss):
    client.force_login(boss)

    response = client.get(NEW_URL)

    assert b"<html" in response.content


def test_assigning_from_the_dialog_reloads_the_page_it_came_from(client, boss, alice):
    client.force_login(boss)

    response = client.post(NEW_URL, {**form_data(alice), "next": "/"}, headers=HTMX)

    assert response["HX-Redirect"] == "/"
    assert Task.objects.get().assigned_to == alice


def test_next_must_stay_on_the_site(client, boss, alice):
    client.force_login(boss)
    data = {**form_data(alice), "next": "https://evil.example/"}

    response = client.post(NEW_URL, data, headers=HTMX)

    assert response["HX-Redirect"] == reverse("tasks:list")


@pytest.mark.parametrize("priority", ["0", "21", ""])
def test_priority_must_be_1_to_20(client, boss, alice, priority):
    client.force_login(boss)

    response = client.post(NEW_URL, form_data(alice, priority=priority), headers=HTMX)

    assert response.status_code == 200
    assert not Task.objects.exists()


def test_description_cannot_be_blank(client, boss, alice):
    client.force_login(boss)

    client.post(NEW_URL, form_data(alice, description="   "), headers=HTMX)

    assert not Task.objects.exists()


def test_completion_date_cannot_be_before_today(client, boss, alice):
    client.force_login(boss)
    yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()

    response = client.post(NEW_URL, form_data(alice, due_date=yesterday), headers=HTMX)

    assert b"before the task was received" in response.content
    assert not Task.objects.exists()


def test_leavers_are_not_offered(client, boss, alice, bob):
    bob.is_active = False
    bob.save()
    client.force_login(boss)

    response = client.get(NEW_URL, headers=HTMX)

    people = list(response.context["form"].fields["assigned_to"].queryset)
    assert alice in people
    assert bob not in people
