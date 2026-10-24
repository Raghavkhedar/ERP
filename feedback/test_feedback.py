import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from notifications.models import Notification

from .models import Area, Attachment, Feedback, Kind, Status
from .services import add_comment, submit, visible_feedback

pytestmark = pytest.mark.django_db

NEW_URL = reverse("feedback:new")
HTMX = {"HX-Request": "true"}
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01"
    b"\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def screenshot(name="screenshot.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


@pytest.fixture
def item(alice, manager):
    return submit(
        alice, Kind.PROBLEM, Area.TASKS, "The task list is slow\nEvery morning"
    )


def texts(user):
    return list(Notification.objects.filter(user=user).values_list("text", flat=True))


# Service


def test_submit_records_who_and_where(alice):
    item = submit(alice, Kind.SUGGESTION, Area.CHAT, "Add emoji", "/chat/")

    assert item.submitter == alice
    assert item.page_url == "/chat/"
    assert item.status == Status.NEW
    assert item.summary == "Add emoji"


def test_submit_tells_every_admin_but_not_others(alice, bob, manager, boss):
    item = submit(alice, Kind.PROBLEM, Area.TASKS, "Broken")

    assert len(texts(manager)) == 1
    assert len(texts(boss)) == 1
    assert texts(bob) == []
    assert texts(alice) == []
    note = Notification.objects.get(user=manager)
    assert note.url == reverse("feedback:detail", args=[item.pk])
    assert "alice" in note.text


def test_an_admin_sending_feedback_is_not_told_about_it(manager, boss):
    submit(manager, Kind.PRAISE, Area.CHAT, "Nice")

    assert texts(manager) == []
    assert len(texts(boss)) == 1


def test_admin_reply_tells_the_submitter_and_starts_the_discussion(
    item, alice, manager
):
    add_comment(item, manager, "Looking into it")

    item.refresh_from_db()
    assert item.status == Status.DISCUSSING
    assert len(texts(alice)) == 1


def test_submitter_reply_tells_the_admins(item, alice, manager, boss):
    Notification.objects.all().delete()
    add_comment(item, alice, "More detail")

    assert len(texts(manager)) == 1
    assert len(texts(boss)) == 1
    assert texts(alice) == []
    item.refresh_from_db()
    assert item.status == Status.NEW


def test_other_admins_who_took_part_hear_replies(item, manager, boss):
    add_comment(item, manager, "First")
    Notification.objects.all().delete()
    add_comment(item, boss, "Second")

    assert len(texts(manager)) == 1


def test_a_stranger_cannot_comment(item, bob):
    with pytest.raises(PermissionDenied):
        add_comment(item, bob, "Hello")


def test_visibility(item, alice, bob, manager):
    assert list(visible_feedback(alice)) == [item]
    assert list(visible_feedback(manager)) == [item]
    assert list(visible_feedback(bob)) == []


# Views


def test_dialog_form_loads_with_the_area_guessed_from_the_page(client, alice):
    client.force_login(alice)

    response = client.get(NEW_URL, {"page": "/tasks/3/"}, headers=HTMX)

    assert response.status_code == 200
    assert response.context["form"].initial["area"] == "tasks"
    assert b"<html" not in response.content


def test_send_feedback_with_a_screenshot(client, alice, manager):
    client.force_login(alice)

    response = client.post(
        NEW_URL,
        {
            "kind": Kind.PROBLEM,
            "area": Area.PLANS,
            "message": "Plan page froze",
            "page": "/plans/",
            "files": screenshot(),
        },
        headers=HTMX,
    )

    item = Feedback.objects.get()
    assert response.headers["HX-Redirect"] == reverse("feedback:detail", args=[item.pk])
    assert item.page_url == "/plans/"
    assert item.attachments.get().is_image
    assert len(texts(manager)) == 1


def test_a_foreign_page_url_is_dropped(client, alice):
    client.force_login(alice)

    client.post(
        NEW_URL,
        {
            "kind": Kind.PRAISE,
            "area": Area.CHAT,
            "message": "Good",
            "page": "https://evil.example/x",
        },
    )

    assert Feedback.objects.get().page_url == ""


def test_blank_message_is_rejected(client, alice):
    client.force_login(alice)

    response = client.post(
        NEW_URL,
        {"kind": Kind.PRAISE, "area": Area.CHAT, "message": "   "},
        headers=HTMX,
    )

    assert response.status_code == 200
    assert not Feedback.objects.exists()
    assert b"Write your feedback" in response.content


def test_list_shows_only_your_own(client, item, bob):
    client.force_login(bob)

    response = client.get(reverse("feedback:list"))

    assert list(response.context["items"]) == []


def test_admin_inbox_shows_everything(client, item, manager):
    client.force_login(manager)

    response = client.get(reverse("feedback:list"))

    assert list(response.context["items"]) == [item]


def test_detail_is_hidden_from_others(client, item, bob):
    client.force_login(bob)

    assert client.get(reverse("feedback:detail", args=[item.pk])).status_code == 404


def test_reply_through_the_page(client, item, manager):
    client.force_login(manager)

    response = client.post(
        reverse("feedback:comment", args=[item.pk]),
        {"body": "On it", "files": screenshot()},
    )

    comment = item.comments.get()
    assert response.status_code == 302
    assert response.url.endswith(f"#comment-{comment.pk}")
    assert comment.attachments.count() == 1


def test_attachments_are_only_served_to_those_who_may_see_them(
    client, alice, bob, manager
):
    item = submit(alice, Kind.PROBLEM, Area.TASKS, "Bad", files=[screenshot()])
    file = Attachment.objects.get()
    url = reverse("feedback:attachment", args=[file.pk])

    client.force_login(bob)
    assert client.get(url).status_code == 404

    for user in (alice, manager):
        client.force_login(user)
        assert client.get(url).status_code == 200
    assert item.attachments.count() == 1


def test_comment_attachments_follow_the_same_rule(client, item, bob, manager):
    comment = add_comment(item, manager, "See this", [screenshot()])
    url = reverse("feedback:attachment", args=[comment.attachments.get().pk])

    client.force_login(bob)
    assert client.get(url).status_code == 404

    client.force_login(manager)
    assert client.get(url).status_code == 200


def test_anonymous_is_sent_to_login(client):
    assert client.get(NEW_URL).status_code == 302
