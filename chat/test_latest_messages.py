import pytest
from django.urls import reverse
from django.utils import timezone

from . import views
from .models import Message
from .test_services import make_channel, make_dm

pytestmark = pytest.mark.django_db


def latest_url(conversation):
    return reverse("chat:latest_messages", args=[conversation.pk])


def post(conversation, author, body):
    return Message.objects.create(conversation=conversation, author=author, body=body)


def test_member_gets_the_messages_as_a_fragment(client, alice):
    general = make_channel("general", alice, members=[alice])
    message = post(general, alice, "hello")
    client.force_login(alice)

    response = client.get(latest_url(general))

    html = response.content.decode()
    assert response.status_code == 200
    assert f'id="message-{message.pk}"' in html
    assert "hello" in html
    assert "<html" not in html


def test_only_the_latest_messages_are_returned_oldest_first(client, alice, monkeypatch):
    monkeypatch.setattr(views, "MESSAGE_LIMIT", 2)
    general = make_channel("general", alice, members=[alice])
    for body in ["first", "second", "third"]:
        post(general, alice, body)
    client.force_login(alice)

    html = client.get(latest_url(general)).content.decode()

    assert "first" not in html
    assert html.index("second") < html.index("third")


def test_public_channel_non_member_cannot_poll(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    client.force_login(bob)
    assert client.get(latest_url(general)).status_code == 403


def test_private_channel_is_404_for_outsiders(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(bob)
    assert client.get(latest_url(secret)).status_code == 404


def test_someone_elses_dm_is_404(client, alice, bob, carol):
    dm = make_dm(alice, bob)
    client.force_login(carol)
    assert client.get(latest_url(dm)).status_code == 404


def test_archived_conversation_is_404(client, alice):
    general = make_channel("general", alice, members=[alice])
    general.archived_at = timezone.now()
    general.save()
    client.force_login(alice)
    assert client.get(latest_url(general)).status_code == 404


def test_post_is_not_allowed(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)
    assert client.post(latest_url(general)).status_code == 405


def test_polling_requires_login(client, alice):
    general = make_channel("general", alice, members=[alice])
    assert client.get(latest_url(general)).status_code == 302


def test_conversation_page_polls_the_endpoint(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)
    html = client.get(
        reverse("chat:conversation_detail", args=[general.pk])
    ).content.decode()
    assert latest_url(general) in html
