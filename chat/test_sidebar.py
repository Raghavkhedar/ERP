import pytest
from django.urls import reverse

from .models import Message
from .services import unread_counts
from .test_services import make_channel

pytestmark = pytest.mark.django_db

SIDEBAR_URL = reverse("chat:sidebar")


def post(conversation, author, body="hi"):
    return Message.objects.create(conversation=conversation, author=author, body=body)


def sidebar_entry(response, conversation):
    entries = response.context["channels"] + response.context["direct_messages"]
    return next(c for c in entries if c.pk == conversation.pk)


def test_sidebar_shows_unread_counts(client, alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    post(general, alice)
    post(general, alice)
    client.force_login(bob)

    response = client.get(SIDEBAR_URL)

    assert response.status_code == 200
    assert sidebar_entry(response, general).unread == 2
    assert "<html" not in response.content.decode()


def test_opening_a_conversation_marks_it_read(client, alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    post(general, alice)
    client.force_login(bob)

    client.get(reverse("chat:conversation_detail", args=[general.pk]))

    assert unread_counts(bob) == {}


def test_polling_an_open_conversation_marks_it_read(client, alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    client.force_login(bob)
    post(general, alice)

    client.get(reverse("chat:latest_messages", args=[general.pk]))

    assert unread_counts(bob) == {}


def test_non_member_can_open_public_channel_without_a_marker(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    post(general, alice)
    client.force_login(bob)
    url = reverse("chat:conversation_detail", args=[general.pk])
    assert client.get(url).status_code == 200


def test_sidebar_remembers_the_open_conversation(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)
    response = client.get(SIDEBAR_URL, {"current": general.pk})
    assert response.context["current_id"] == general.pk


def test_sidebar_ignores_a_bad_current_value(client, alice):
    client.force_login(alice)
    response = client.get(SIDEBAR_URL, {"current": "abc"})
    assert response.status_code == 200
    assert response.context["current_id"] is None


def test_sidebar_requires_login(client):
    assert client.get(SIDEBAR_URL).status_code == 302


def test_sidebar_only_allows_get(client, alice):
    client.force_login(alice)
    assert client.post(SIDEBAR_URL).status_code == 405


def test_conversation_page_polls_the_sidebar(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)
    html = client.get(
        reverse("chat:conversation_detail", args=[general.pk])
    ).content.decode()
    assert f"{SIDEBAR_URL}?current={general.pk}" in html
