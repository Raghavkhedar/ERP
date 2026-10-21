import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from .models import Membership
from .services import unread_counts, visible_conversations
from .test_services import make_channel, make_dm

pytestmark = pytest.mark.django_db


@pytest.fixture
def office_admin(django_user_model):
    user = django_user_model.objects.create_user(
        username="manager", password="pw", is_staff=True
    )
    user.groups.add(Group.objects.get(name="Office admin"))
    return user


def people_url(conversation):
    return reverse("chat:add_people", args=[conversation.pk])


def add_url(conversation, user):
    return reverse("chat:add_person", args=[conversation.pk, user.pk])


def detail_url(conversation):
    return reverse("chat:conversation_detail", args=[conversation.pk])


def test_creator_can_add_someone_to_a_private_channel(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(alice)

    response = client.post(add_url(secret, bob))

    assert response.status_code == 302
    assert response.url == people_url(secret)
    assert Membership.objects.filter(conversation=secret, user=bob).exists()
    assert secret in visible_conversations(bob)


def test_adding_posts_a_system_message_by_whoever_added(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(alice)

    client.post(add_url(secret, bob))

    message = secret.messages.get()
    assert message.is_system
    assert message.author == alice
    assert message.body == "added bob"


def test_added_person_sees_the_announcement_but_no_unread_badge(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(alice)
    client.post(add_url(secret, bob))

    client.force_login(bob)
    html = client.get(detail_url(secret)).content.decode()

    assert "alice added bob" in " ".join(html.split())
    assert unread_counts(bob) == {}


def test_adding_twice_keeps_one_membership_and_one_message(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(alice)

    client.post(add_url(secret, bob))
    client.post(add_url(secret, bob))

    assert Membership.objects.filter(conversation=secret, user=bob).count() == 1
    assert secret.messages.count() == 1


def test_office_admin_member_can_add_people(client, alice, bob, office_admin):
    secret = make_channel(
        "secret", alice, members=[alice, office_admin], is_private=True
    )
    client.force_login(office_admin)

    client.post(add_url(secret, bob))

    assert Membership.objects.filter(conversation=secret, user=bob).exists()


def test_other_members_cannot_add_people(client, alice, bob, carol):
    secret = make_channel("secret", alice, members=[alice, bob], is_private=True)
    client.force_login(bob)

    assert client.get(people_url(secret)).status_code == 403
    assert client.post(add_url(secret, carol)).status_code == 403
    assert not Membership.objects.filter(conversation=secret, user=carol).exists()


def test_non_members_cannot_find_a_private_channel(client, alice, bob, carol):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(bob)

    assert client.get(people_url(secret)).status_code == 404
    assert client.post(add_url(secret, carol)).status_code == 404


def test_public_channels_and_dms_have_no_add_people(client, alice, bob, carol):
    general = make_channel("general", alice, members=[alice])
    dm = make_dm(alice, bob)
    client.force_login(alice)

    for conversation in (general, dm):
        assert client.get(people_url(conversation)).status_code == 403
        assert client.post(add_url(conversation, carol)).status_code == 403
    assert not Membership.objects.filter(user=carol).exists()


def test_people_page_lists_only_active_non_members(
    client, alice, bob, carol, django_user_model
):
    secret = make_channel("secret", alice, members=[alice, bob], is_private=True)
    django_user_model.objects.create_user(
        username="gone", password="pw", is_active=False
    )
    client.force_login(alice)

    response = client.get(people_url(secret))

    assert [p.username for p in response.context["people"]] == ["carol"]


def test_inactive_people_cannot_be_added(client, alice, django_user_model):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    gone = django_user_model.objects.create_user(
        username="gone", password="pw", is_active=False
    )
    client.force_login(alice)

    assert client.post(add_url(secret, gone)).status_code == 404
    assert not Membership.objects.filter(user=gone).exists()


def test_add_people_link_is_shown_only_to_those_who_can_add(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice, bob], is_private=True)

    client.force_login(alice)
    assert people_url(secret) in client.get(detail_url(secret)).content.decode()

    client.force_login(bob)
    assert people_url(secret) not in client.get(detail_url(secret)).content.decode()


def test_adding_is_recorded_in_history_with_who_did_it(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)
    client.force_login(alice)

    client.post(add_url(secret, bob))

    membership = Membership.objects.get(conversation=secret, user=bob)
    assert membership.history.get().history_user == alice


def test_adding_requires_post_and_login(client, alice, bob):
    secret = make_channel("secret", alice, members=[alice], is_private=True)

    assert client.post(add_url(secret, bob)).status_code == 302
    client.force_login(alice)
    assert client.get(add_url(secret, bob)).status_code == 405
    assert not Membership.objects.filter(user=bob).exists()
