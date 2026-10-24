from datetime import datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .models import Conference
from .services import create_conference, respond
from .test_calendar import cell, day_url, month_url
from .testing import open_slots

pytestmark = pytest.mark.django_db

DAY = timezone.localdate() + timedelta(days=1)


def at(hour, minute=0):
    return timezone.make_aware(datetime.combine(DAY, time(hour, minute)))


@pytest.fixture
def conference(alice, bob, carol):
    return create_conference(
        alice, "Quarterly review", at(10), at(11), [bob, carol], location="Room 2"
    )


def detail(conference):
    return reverse("meetings:conference_detail", args=[conference.pk])


def post_new(client, people, **extra):
    data = {
        "title": "Planning",
        "day": DAY.isoformat(),
        "start": "10:00",
        "end": "11:00",
        "invitees": [p.pk for p in people],
        **extra,
    }
    return client.post(reverse("meetings:conference_new"), data)


def test_creating_a_conference(client, alice, bob):
    client.force_login(alice)

    response = post_new(client, [bob], location="Room 1", agenda="Budget")

    conference = Conference.objects.get()
    assert response.status_code == 302 and response.url == detail(conference)
    assert conference.host == alice and conference.location == "Room 1"
    assert conference.invitations.get().user == bob


def test_creating_needs_someone_to_invite(client, alice):
    client.force_login(alice)
    assert post_new(client, []).status_code == 200
    assert not Conference.objects.exists()


def test_a_clash_asks_before_creating(client, alice, bob, carol):
    [slot] = open_slots(bob, DAY, time(10), time(10, 30), 30)
    from .services import book

    book(slot, carol, "Chat")
    client.force_login(alice)

    first = post_new(client, [bob])
    assert first.status_code == 200 and first.context["clashes"] == [bob]
    assert not Conference.objects.exists()

    assert post_new(client, [bob], confirm="1").status_code == 302
    assert Conference.objects.count() == 1


def test_invitee_can_answer_from_the_detail_page(client, conference, bob):
    client.force_login(bob)
    assert "Accept" in client.get(detail(conference)).content.decode()

    client.post(
        reverse("meetings:conference_respond", args=[conference.pk]),
        {"answer": "accept"},
    )
    assert conference.invitations.get(user=bob).status == "accepted"


def test_strangers_cannot_see_a_conference(client, conference, django_user_model):
    dan = django_user_model.objects.create_user(username="dan", password="pw")
    client.force_login(dan)
    assert client.get(detail(conference)).status_code == 404


def test_only_the_host_can_cancel(client, conference, alice, bob):
    url = reverse("meetings:conference_cancel", args=[conference.pk])
    client.force_login(bob)
    assert client.post(url).status_code == 403

    client.force_login(alice)
    assert client.post(url).status_code == 302
    conference.refresh_from_db()
    assert conference.is_cancelled


def test_list_groups_by_what_you_need_to_do(client, conference, alice, bob):
    client.force_login(bob)
    assert client.get(reverse("meetings:conferences")).context["waiting"] == [
        conference
    ]
    respond(conference, bob, True)
    assert client.get(reverse("meetings:conferences")).context["going"] == [conference]
    client.force_login(alice)
    assert client.get(reverse("meetings:conferences")).context["hosting"] == [
        conference
    ]


def test_calendar_shows_conferences_to_host_and_invitees(
    client, conference, alice, bob, carol
):
    respond(conference, carol, False)
    for person, shown in ((alice, True), (bob, True), (carol, False)):
        client.force_login(person)
        month = client.get(month_url(DAY))
        assert bool(cell(month, DAY)["conferences"]) is shown
        day = client.get(day_url(DAY))
        assert ("Quarterly review" in day.content.decode()) is shown


def test_free_slots_under_a_conference_are_hidden(client, conference, alice, bob):
    respond(conference, bob, True)
    open_slots(bob, DAY, time(10), time(11), 15)
    after = open_slots(bob, DAY, time(11), time(11, 15), 15)

    client.force_login(alice)
    response = client.get(reverse("meetings:person_slots", args=[bob.pk]))
    assert list(response.context["slots"]) == after

    client.force_login(bob)
    assert cell(client.get(month_url(DAY)), DAY)["free"] == 1


def test_host_can_invite_more_and_remove(client, conference, alice, django_user_model):
    dan = django_user_model.objects.create_user(username="dan", password="pw")
    client.force_login(alice)
    client.post(
        reverse("meetings:conference_invite", args=[conference.pk]),
        {"invitees": [dan.pk]},
    )
    assert conference.invitations.filter(user=dan).exists()

    client.post(reverse("meetings:conference_remove", args=[conference.pk, dan.pk]))
    assert not conference.invitations.filter(user=dan).exists()


def test_people_page_only_says_available_or_not(client, conference, alice, bob):
    respond(conference, bob, True)
    open_slots(bob, DAY, time(10), time(11), 15)
    client.force_login(alice)

    response = client.get(reverse("meetings:people"))
    assert {p.first_name: p.available for p in response.context["people"]}[
        "bob"
    ] is False
    assert "No slots available" in response.content.decode()
    assert "free slot" not in response.content.decode()

    open_slots(bob, DAY, time(12), time(12, 15), 15)
    response = client.get(reverse("meetings:people"))
    assert {p.first_name: p.available for p in response.context["people"]}["bob"]
