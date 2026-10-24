import pytest
from django.urls import reverse

from chat.services import post_notice
from notifications.models import Notification
from notifications.services import (
    mark_all_read,
    mark_read,
    notify,
    since,
    unread_count,
)

pytestmark = pytest.mark.django_db


def test_notify_creates_for_the_recipient_only(alice, bob):
    notify(bob, "Hello", "/tasks/")
    assert Notification.objects.get().user == bob
    assert unread_count(alice) == 0
    assert unread_count(bob) == 1


def test_inactive_accounts_are_skipped(alice):
    alice.is_active = False
    alice.save()
    assert notify(alice, "Hello") is None
    assert not Notification.objects.exists()


def test_long_text_is_cut_to_fit(alice):
    notify(alice, "x" * 500)
    assert len(Notification.objects.get().text) <= 300


def test_mark_read_only_touches_the_users_own(alice, bob):
    theirs = notify(bob, "Hello")
    assert mark_read(alice, theirs.pk) is None
    theirs.refresh_from_db()
    assert theirs.read_at is None


def test_mark_all_read(alice, bob):
    notify(alice, "one")
    notify(alice, "two")
    notify(bob, "three")
    mark_all_read(alice)
    assert unread_count(alice) == 0
    assert unread_count(bob) == 1


def test_since_is_oldest_first_and_capped(alice):
    made = [notify(alice, str(i)) for i in range(15)]
    got = since(alice, made[2].id)
    assert [n.id for n in got] == [n.id for n in made[3:13]]


def test_post_notice_also_notifies(alice, bob):
    post_notice(alice, bob, "Booked your slot")
    notification = Notification.objects.get()
    assert notification.user == bob
    assert notification.text == "Booked your slot"
    assert notification.url.startswith("/chat/")
    assert unread_count(alice) == 0


def test_pulse_returns_only_new_items_for_me(client, alice, bob):
    first = notify(alice, "one")
    second = notify(alice, "two")
    notify(bob, "not yours")
    client.force_login(alice)
    data = client.get(reverse("notifications:pulse"), {"after": first.id}).json()
    assert data["unread"] == 2
    assert data["latest"] == second.id
    assert [item["text"] for item in data["items"]] == ["two"]
    assert data["items"][0]["url"] == reverse("notifications:open", args=[second.pk])


def test_pulse_without_after_returns_no_items(client, alice):
    notify(alice, "one")
    client.force_login(alice)
    assert client.get(reverse("notifications:pulse")).json()["items"] == []


def test_pulse_needs_login(client):
    assert client.get(reverse("notifications:pulse")).status_code == 302


def test_open_marks_read_and_redirects(client, alice):
    n = notify(alice, "one", "/tasks/")
    client.force_login(alice)
    response = client.get(reverse("notifications:open", args=[n.pk]))
    assert response.status_code == 302 and response.url == "/tasks/"
    n.refresh_from_db()
    assert n.read_at is not None


def test_open_never_leaves_the_site(client, alice):
    n = notify(alice, "one", "https://evil.example/phish")
    client.force_login(alice)
    response = client.get(reverse("notifications:open", args=[n.pk]))
    assert response.url == reverse("home")


def test_cannot_open_someone_elses(client, alice, bob):
    n = notify(bob, "private", "/tasks/")
    client.force_login(alice)
    assert client.get(reverse("notifications:open", args=[n.pk])).status_code == 404
    n.refresh_from_db()
    assert n.read_at is None


def test_dropdown_lists_my_notifications(client, alice, bob):
    notify(alice, "Mine")
    notify(bob, "Theirs")
    client.force_login(alice)
    body = client.get(reverse("notifications:list")).content.decode()
    assert "Mine" in body and "Theirs" not in body


def test_read_all_view(client, alice):
    notify(alice, "one")
    client.force_login(alice)
    assert client.post(reverse("notifications:read_all")).status_code == 200
    assert unread_count(alice) == 0


def test_pages_carry_the_bell_and_notifier(client, alice):
    client.force_login(alice)
    body = client.get(reverse("home")).content.decode()
    assert reverse("notifications:pulse") in body
    assert 'aria-label="Notifications"' in body


def test_login_page_has_neither(client):
    body = client.get(reverse("login")).content.decode()
    assert reverse("notifications:pulse") not in body
