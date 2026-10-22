import pytest
from django.urls import reverse

from .models import Message, MessageKind
from .services import newest_incoming, post_notice
from .test_services import make_channel

pytestmark = pytest.mark.django_db

PULSE_URL = reverse("chat:pulse")


def post(conversation, author, body="hi", kind=MessageKind.USER):
    return Message.objects.create(
        conversation=conversation, author=author, body=body, kind=kind
    )


def test_newest_incoming_is_the_latest_message_from_someone_else(alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    first = post(general, alice)
    post(general, bob)

    assert newest_incoming(bob) == first.id


def test_newest_incoming_ignores_system_messages(alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    post(general, alice, "joined", kind=MessageKind.SYSTEM)

    assert newest_incoming(bob) is None


def test_newest_incoming_ignores_conversations_the_user_is_not_in(alice, bob, carol):
    secret = make_channel("secret", alice, members=[alice, carol], is_private=True)
    post(secret, alice)

    assert newest_incoming(bob) is None


def test_notices_count(alice, bob):
    notice = post_notice(alice, bob, "Booked your slot")

    assert newest_incoming(bob) == notice.id


def test_pulse_returns_unread_total_and_newest(client, alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    post(general, alice)
    notice = post_notice(alice, bob, "Booked your slot")
    client.force_login(bob)

    response = client.get(PULSE_URL)

    assert response.status_code == 200
    assert response.json() == {"unread": 2, "newest": notice.id}


def test_pulse_with_nothing_new(client, bob):
    client.force_login(bob)

    assert client.get(PULSE_URL).json() == {"unread": 0, "newest": None}


def test_pulse_needs_login(client):
    response = client.get(PULSE_URL)

    assert response.status_code == 302


def test_chat_button_on_pages_but_not_in_chat(client, bob):
    client.force_login(bob)

    home = client.get(reverse("home")).content.decode()
    chat = client.get(reverse("chat:conversation_list")).content.decode()

    assert 'title="Chat"' in home
    assert PULSE_URL in home
    assert 'title="Chat"' not in chat
    assert PULSE_URL in chat  # the bell still rings inside chat


def test_no_chat_button_when_logged_out(client):
    html = client.get(reverse("login")).content.decode()

    assert PULSE_URL not in html
