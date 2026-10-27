import pytest
from django.urls import reverse

from chat.models import Conversation, ConversationKind, Message
from tasks.models import Task, TaskUpdate
from tasks.services import add_update, assign

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_superuser(
        username="boss", password="pw", first_name="boss"
    )


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="alice", password="pw", first_name="alice"
    )


@pytest.fixture
def task(boss, alice):
    from datetime import timedelta

    from django.utils import timezone

    task = assign(
        boss, alice, 3, "Audit report", timezone.localdate() + timedelta(days=3)
    )
    add_update(task, alice, "Collected the statements")
    return task


def test_superadmin_can_delete_a_single_log_entry(client, boss, task):
    update = TaskUpdate.objects.get()
    client.force_login(boss)

    response = client.post(
        reverse("admin:tasks_taskupdate_delete", args=[update.pk]), {"post": "yes"}
    )

    assert response.status_code == 302
    assert not TaskUpdate.objects.exists()
    assert Task.objects.filter(pk=task.pk).exists()


def test_superadmin_can_delete_a_task_with_its_log(client, boss, task):
    client.force_login(boss)

    response = client.post(
        reverse("admin:tasks_task_delete", args=[task.pk]), {"post": "yes"}
    )

    assert response.status_code == 302
    assert not Task.objects.exists()
    assert not TaskUpdate.objects.exists()


def test_superadmin_can_edit_a_log_entry(client, boss, task):
    update = TaskUpdate.objects.get()
    client.force_login(boss)

    response = client.post(
        reverse("admin:tasks_taskupdate_change", args=[update.pk]),
        {"task": task.pk, "author": update.author_id, "body": "Fixed wording"},
    )

    assert response.status_code == 302
    update.refresh_from_db()
    assert update.body == "Fixed wording"


def test_superadmin_can_delete_chat_messages_and_conversations(client, boss, alice):
    conversation = Conversation.objects.create(
        kind=ConversationKind.CHANNEL, name="Team", created_by=boss
    )
    message = Message.objects.create(conversation=conversation, author=alice, body="hi")
    client.force_login(boss)

    client.post(
        reverse("admin:chat_message_delete", args=[message.pk]), {"post": "yes"}
    )
    assert not Message.objects.exists()

    Message.objects.create(conversation=conversation, author=alice, body="again")
    client.post(
        reverse("admin:chat_conversation_delete", args=[conversation.pk]),
        {"post": "yes"},
    )
    assert not Conversation.objects.exists()
    assert not Message.objects.exists()


def test_people_cannot_be_deleted_out_from_under_their_work(client, boss, task, alice):
    """Deleting a person is still refused while they have tasks: deactivate instead."""
    client.force_login(boss)

    response = client.post(
        reverse("admin:core_user_delete", args=[alice.pk]), {"post": "yes"}
    )

    assert response.status_code == 200  # the "protected objects" page
    assert type(alice).objects.filter(pk=alice.pk).exists()
