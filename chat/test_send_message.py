import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from .models import Message
from .test_services import make_channel, make_dm

pytestmark = pytest.mark.django_db

HTMX = {"HX-Request": "true"}


def send_url(conversation):
    return reverse("chat:send_message", args=[conversation.pk])


def detail_url(conversation):
    return reverse("chat:conversation_detail", args=[conversation.pk])


def test_member_message_is_saved_with_them_as_author(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)

    client.post(send_url(general), {"body": "hello"})

    message = Message.objects.get()
    assert message.conversation == general
    assert message.author == alice
    assert message.body == "hello"


def test_plain_post_redirects_back_to_the_conversation(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)
    response = client.post(send_url(general), {"body": "hello"})
    assert response.status_code == 302
    assert response.url == detail_url(general)


def test_htmx_post_returns_only_the_new_message(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)

    response = client.post(send_url(general), {"body": "hello"}, headers=HTMX)

    html = response.content.decode()
    assert response.status_code == 200
    assert "hello" in html
    assert "<html" not in html


@pytest.mark.parametrize("body", ["", "   ", "x" * 4001])
def test_invalid_body_is_rejected(client, alice, body):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)
    assert client.post(send_url(general), {"body": body}).status_code == 400
    assert not Message.objects.exists()


def test_author_and_conversation_come_from_the_server(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    other = make_channel("other", bob, members=[bob])
    client.force_login(alice)

    client.post(
        send_url(general),
        {"body": "hi", "author": bob.pk, "conversation": other.pk},
    )

    message = Message.objects.get()
    assert message.author == alice
    assert message.conversation == general


def test_non_member_cannot_send_to_public_channel(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    client.force_login(bob)
    assert client.post(send_url(general), {"body": "hi"}).status_code == 403
    assert not Message.objects.exists()


def test_private_channel_is_404_for_outsiders(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(bob)
    assert client.post(send_url(secret), {"body": "hi"}).status_code == 404


def test_someone_elses_dm_is_404(client, alice, bob, carol):
    dm = make_dm(alice, bob)
    client.force_login(carol)
    assert client.post(send_url(dm), {"body": "hi"}).status_code == 404


def test_archived_conversation_is_404(client, alice):
    general = make_channel("general", alice, members=[alice])
    general.archived_at = timezone.now()
    general.save()
    client.force_login(alice)
    assert client.post(send_url(general), {"body": "hi"}).status_code == 404


def test_get_is_not_allowed(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)
    assert client.get(send_url(general)).status_code == 405


def test_sending_requires_login(client, alice):
    general = make_channel("general", alice, members=[alice])
    assert client.post(send_url(general), {"body": "hi"}).status_code == 302
    assert not Message.objects.exists()


def test_message_box_is_shown_to_members_only(client, alice, bob):
    general = make_channel("general", alice, members=[alice])

    client.force_login(alice)
    assert send_url(general) in client.get(detail_url(general)).content.decode()

    client.force_login(bob)
    assert send_url(general) not in client.get(detail_url(general)).content.decode()


def test_sending_works_with_csrf_checks_on(alice):
    general = make_channel("general", alice, members=[alice])
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(alice)
    browser.get(detail_url(general))
    token = browser.cookies["csrftoken"].value

    response = browser.post(
        send_url(general), {"body": "hi", "csrfmiddlewaretoken": token}, headers=HTMX
    )

    assert response.status_code == 200


def test_sending_without_csrf_token_is_rejected(alice):
    general = make_channel("general", alice, members=[alice])
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(alice)
    response = browser.post(send_url(general), {"body": "hi"}, headers=HTMX)
    assert response.status_code == 403
    assert not Message.objects.exists()
