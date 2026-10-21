import pytest
from django.urls import reverse

from .models import Conversation, ConversationKind, Membership
from .services import get_or_create_dm

pytestmark = pytest.mark.django_db

NEW_DM_URL = reverse("chat:new_dm")


def open_url(user):
    return reverse("chat:open_dm", args=[user.pk])


def test_starting_a_dm_creates_it_with_both_people(alice, bob):
    dm = get_or_create_dm(alice, bob)

    assert dm.kind == ConversationKind.DIRECT
    assert dm.created_by == alice
    members = set(dm.memberships.values_list("user__username", flat=True))
    assert members == {"alice", "bob"}


def test_the_same_pair_always_gets_the_same_dm(alice, bob):
    first = get_or_create_dm(alice, bob)
    assert get_or_create_dm(alice, bob) == first
    assert get_or_create_dm(bob, alice) == first
    assert Conversation.objects.count() == 1
    assert Membership.objects.count() == 2


def test_a_dm_with_yourself_has_one_member(alice):
    dm = get_or_create_dm(alice, alice)
    assert list(dm.memberships.values_list("user__username", flat=True)) == ["alice"]


def test_message_button_opens_the_dm(client, alice, bob):
    client.force_login(alice)

    response = client.post(open_url(bob))

    dm = Conversation.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("chat:conversation_detail", args=[dm.pk])


def test_new_dm_is_recorded_in_history_with_who_started_it(client, alice, bob):
    client.force_login(alice)
    client.post(open_url(bob))
    assert Conversation.objects.get().history.get().history_user == alice


def test_cannot_message_an_inactive_person(client, alice, bob):
    bob.is_active = False
    bob.save()
    client.force_login(alice)
    assert client.post(open_url(bob)).status_code == 404
    assert not Conversation.objects.exists()


def test_people_list_shows_active_people_except_you(
    client, alice, bob, carol, django_user_model
):
    django_user_model.objects.create_user(username="gone", is_active=False)
    client.force_login(alice)

    people = client.get(NEW_DM_URL).context["people"]

    assert [p.username for p in people] == ["bob", "carol"]


def test_sidebar_links_to_new_dm(client, alice):
    client.force_login(alice)
    html = client.get(reverse("chat:conversation_list")).content.decode()
    assert NEW_DM_URL in html


def test_open_dm_only_allows_post(client, alice, bob):
    client.force_login(alice)
    assert client.get(open_url(bob)).status_code == 405


def test_dm_pages_require_login(client, bob):
    assert client.get(NEW_DM_URL).status_code == 302
    assert client.post(open_url(bob)).status_code == 302
