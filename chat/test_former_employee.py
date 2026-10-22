import pytest
from django.urls import reverse

from .models import Message
from .services import add_member, conversation_title
from .test_services import make_channel, make_dm

pytestmark = pytest.mark.django_db


def leave(user):
    user.is_active = False
    user.save()


def page(client, conversation):
    html = client.get(reverse("chat:conversation_detail", args=[conversation.pk]))
    return " ".join(html.content.decode().split())


def test_leavers_are_shown_as_former_employee(bob):
    leave(bob)
    assert bob.display_name == "Former employee"


def test_a_leavers_messages_show_former_employee(client, alice, bob):
    general = make_channel("general", alice, members=[alice, bob])
    Message.objects.create(conversation=general, author=bob, body="see you")
    leave(bob)
    client.force_login(alice)

    html = page(client, general)

    assert "Former employee" in html
    assert "see you" in html
    assert ">bob<" not in html


def test_added_announcement_shows_former_employee_after_they_leave(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    add_member(secret, alice, bob)
    leave(bob)
    client.force_login(alice)

    assert "alice added Former employee" in page(client, secret)


def test_dm_with_a_leaver_is_titled_former_employee(alice, bob):
    dm = make_dm(alice, bob)
    leave(bob)
    assert conversation_title(dm, alice) == "Former employee"
