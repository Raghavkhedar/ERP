import pytest
from django.urls import reverse

from .models import Conversation, ConversationKind, Membership
from .services import visible_conversations
from .test_services import make_channel

pytestmark = pytest.mark.django_db

NEW_CHANNEL_URL = reverse("chat:new_channel")


def create(client, name, is_private=False):
    data = {"name": name}
    if is_private:
        data["is_private"] = "on"
    return client.post(NEW_CHANNEL_URL, data)


def test_creating_a_channel_makes_you_its_first_member(client, alice):
    client.force_login(alice)

    response = create(client, "leads")

    channel = Conversation.objects.get()
    assert channel.kind == ConversationKind.CHANNEL
    assert channel.name == "leads"
    assert not channel.is_private
    assert channel.created_by == alice
    assert list(Membership.objects.values_list("user__username", flat=True)) == [
        "alice"
    ]
    assert response.status_code == 302
    assert response.url == reverse("chat:conversation_detail", args=[channel.pk])


def test_creating_a_channel_posts_a_system_message(client, alice):
    client.force_login(alice)

    create(client, "leads")

    message = Conversation.objects.get().messages.get()
    assert message.is_system
    assert message.author == alice
    assert message.body == "created the channel"


def test_private_channel_is_hidden_from_everyone_else(client, alice, bob):
    client.force_login(alice)

    create(client, "secret", is_private=True)

    secret = Conversation.objects.get()
    assert secret.is_private
    assert secret not in visible_conversations(bob)


def test_a_leading_hash_is_dropped(client, alice):
    client.force_login(alice)

    create(client, "#leads")

    assert Conversation.objects.get().name == "leads"


def test_names_must_be_unique_ignoring_case(client, alice):
    make_channel("Leads", alice)
    client.force_login(alice)

    response = create(client, "leads")

    assert response.status_code == 200
    assert "already exists" in response.content.decode()
    assert Conversation.objects.count() == 1


@pytest.mark.parametrize("name", ["", "   ", "#"])
def test_a_name_is_required(client, alice, name):
    client.force_login(alice)

    response = create(client, name)

    assert response.status_code == 200
    assert response.context["form"].errors["name"]
    assert not Conversation.objects.exists()


def test_new_channel_is_recorded_in_history_with_who_created_it(client, alice):
    client.force_login(alice)

    create(client, "leads")

    assert Conversation.objects.get().history.get().history_user == alice


def test_sidebar_links_to_new_channel(client, alice):
    client.force_login(alice)

    html = client.get(reverse("chat:conversation_list")).content.decode()

    assert NEW_CHANNEL_URL in html


def test_new_channel_page_requires_login(client):
    assert client.get(NEW_CHANNEL_URL).status_code == 302
    assert client.post(NEW_CHANNEL_URL, {"name": "leads"}).status_code == 302
    assert not Conversation.objects.exists()
