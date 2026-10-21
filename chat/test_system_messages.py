import pytest
from django.urls import reverse

from .models import Message, MessageKind
from .services import join, unread_counts
from .test_services import make_channel

pytestmark = pytest.mark.django_db


def test_joining_posts_a_system_message(alice, bob):
    general = make_channel("general", alice, members=[alice])

    join(general, bob)

    message = Message.objects.get()
    assert message.conversation == general
    assert message.author == bob
    assert message.is_system
    assert message.body == "joined the channel"


def test_joining_twice_posts_one_system_message(alice, bob):
    general = make_channel("general", alice, members=[alice])
    join(general, bob)
    join(general, bob)
    assert Message.objects.filter(kind=MessageKind.SYSTEM).count() == 1


def test_system_messages_do_not_count_as_unread(alice, bob):
    general = make_channel("general", alice, members=[alice])
    join(general, bob)
    assert unread_counts(alice) == {}


def test_ordinary_messages_still_count_after_a_join(alice, bob):
    general = make_channel("general", alice, members=[alice])
    join(general, bob)
    Message.objects.create(conversation=general, author=bob, body="hello")
    assert unread_counts(alice) == {general.pk: 1}


def test_members_see_who_joined(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    client.force_login(bob)

    client.post(reverse("chat:join", args=[general.pk]))

    client.force_login(alice)
    url = reverse("chat:conversation_detail", args=[general.pk])
    assert "bob joined the channel" in client.get(url).content.decode()


def test_new_messages_are_ordinary_by_default(alice):
    general = make_channel("general", alice, members=[alice])
    message = Message.objects.create(conversation=general, author=alice, body="hi")
    assert message.kind == MessageKind.USER
    assert not message.is_system
