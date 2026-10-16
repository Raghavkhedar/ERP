import pytest
from django.urls import reverse
from django.utils import timezone

from .models import Message
from .test_services import make_channel, make_dm

pytestmark = pytest.mark.django_db


def detail_url(conversation):
    return reverse("chat:conversation_detail", args=[conversation.pk])


def test_chat_requires_login(client):
    response = client.get(reverse("chat:conversation_list"))
    assert response.status_code == 302


def test_sidebar_lists_visible_conversations_only(client, alice, bob, carol):
    make_channel("general", carol)
    make_channel("secret", carol, members=[carol], is_private=True)
    make_dm(alice, bob)
    client.force_login(alice)

    html = client.get(reverse("chat:conversation_list")).content.decode()

    assert "#general" in html
    assert "bob" in html
    assert "secret" not in html


def test_member_can_open_private_channel(client, alice):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(alice)
    assert client.get(detail_url(secret)).status_code == 200


def test_private_channel_is_404_for_outsiders(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(bob)
    assert client.get(detail_url(secret)).status_code == 404


def test_someone_elses_dm_is_404(client, alice, bob, carol):
    dm = make_dm(alice, bob)
    client.force_login(carol)
    assert client.get(detail_url(dm)).status_code == 404


def test_public_channel_opens_for_non_members(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    client.force_login(bob)
    assert client.get(detail_url(general)).status_code == 200


def test_archived_conversation_is_404(client, alice):
    general = make_channel("general", alice, members=[alice])
    general.archived_at = timezone.now()
    general.save()
    client.force_login(alice)
    assert client.get(detail_url(general)).status_code == 404


def test_messages_are_shown_oldest_first(client, alice):
    general = make_channel("general", alice, members=[alice])
    Message.objects.create(conversation=general, author=alice, body="message-one")
    Message.objects.create(conversation=general, author=alice, body="message-two")
    client.force_login(alice)

    html = client.get(detail_url(general)).content.decode()

    assert html.index("message-one") < html.index("message-two")


def test_message_html_is_escaped(client, alice):
    general = make_channel("general", alice, members=[alice])
    Message.objects.create(
        conversation=general, author=alice, body="<script>alert(1)</script>"
    )
    client.force_login(alice)

    html = client.get(detail_url(general)).content.decode()

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_dm_page_is_titled_with_the_other_person(client, alice, bob):
    dm = make_dm(alice, bob)
    client.force_login(alice)
    response = client.get(detail_url(dm))
    assert response.context["title"] == "bob"
