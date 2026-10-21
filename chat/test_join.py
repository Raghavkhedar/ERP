import pytest
from django.urls import reverse
from django.utils import timezone

from .models import Membership, Message
from .test_services import make_channel, make_dm

pytestmark = pytest.mark.django_db


def join_url(conversation):
    return reverse("chat:join", args=[conversation.pk])


def detail_url(conversation):
    return reverse("chat:conversation_detail", args=[conversation.pk])


def test_joining_a_public_channel_makes_you_a_member(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    client.force_login(bob)

    response = client.post(join_url(general))

    assert response.status_code == 302
    assert response.url == detail_url(general)
    assert Membership.objects.filter(conversation=general, user=bob).exists()


def test_joining_twice_keeps_one_membership(client, alice):
    general = make_channel("general", alice, members=[alice])
    client.force_login(alice)
    client.post(join_url(general))
    assert Membership.objects.filter(conversation=general, user=alice).count() == 1


def test_join_is_recorded_in_history_with_who_did_it(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    client.force_login(bob)

    client.post(join_url(general))

    membership = Membership.objects.get(conversation=general, user=bob)
    assert membership.history.get().history_user == bob


def test_after_joining_the_message_box_appears(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    client.force_login(bob)
    join_button = f'action="{join_url(general)}"'
    assert join_button in client.get(detail_url(general)).content.decode()

    client.post(join_url(general))

    html = client.get(detail_url(general)).content.decode()
    assert join_button not in html
    assert 'name="body"' in html


def test_non_member_sees_no_messages_until_they_join(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    Message.objects.create(conversation=general, author=alice, body="plans")
    client.force_login(bob)
    assert "plans" not in client.get(detail_url(general)).content.decode()

    client.post(join_url(general))

    assert "plans" in client.get(detail_url(general)).content.decode()


def test_private_channel_cannot_be_joined_by_outsiders(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(bob)
    assert client.post(join_url(secret)).status_code == 404
    assert not Membership.objects.filter(user=bob).exists()


def test_someone_elses_dm_cannot_be_joined(client, alice, bob, carol):
    dm = make_dm(alice, bob)
    client.force_login(carol)
    assert client.post(join_url(dm)).status_code == 404
    assert not Membership.objects.filter(user=carol).exists()


def test_archived_channel_cannot_be_joined(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    general.archived_at = timezone.now()
    general.save()
    client.force_login(bob)
    assert client.post(join_url(general)).status_code == 404


def test_join_only_allows_post(client, alice, bob):
    general = make_channel("general", alice, members=[alice])
    client.force_login(bob)
    assert client.get(join_url(general)).status_code == 405


def test_join_requires_login(client, alice):
    general = make_channel("general", alice, members=[alice])
    assert client.post(join_url(general)).status_code == 302
    assert Membership.objects.count() == 1
