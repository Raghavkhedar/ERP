import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from notifications.models import Notification

from .models import Area, Attachment, Feedback, Kind, Lesson, Outcome, Status
from .services import (
    FeedbackError,
    add_comment,
    search_lessons,
    set_resolution,
    submit,
    visible_feedback,
)

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


# Resolution


def resolve_url(item):
    return reverse("feedback:resolve", args=[item.pk])


def test_resolving_needs_an_outcome(item, manager):
    with pytest.raises(FeedbackError):
        set_resolution(item, manager, Status.RESOLVED, "")

    item.refresh_from_db()
    assert item.status == Status.NEW


def test_resolving_tells_the_submitter_once(item, alice, manager):
    set_resolution(item, manager, Status.RESOLVED, Outcome.SOFTWARE_FIX)
    set_resolution(item, manager, Status.RESOLVED, Outcome.SOFTWARE_FIX)

    item.refresh_from_db()
    assert item.status == Status.RESOLVED
    assert len(texts(alice)) == 1
    assert "fixed in the software" in texts(alice)[0]


def test_only_admins_change_the_resolution(item, alice):
    with pytest.raises(PermissionDenied):
        set_resolution(item, alice, Status.RESOLVED, Outcome.NOTHING)


def test_resolve_through_the_page(client, item, manager):
    client.force_login(manager)

    response = client.post(
        resolve_url(item), {"status": "resolved", "outcome": "lesson"}
    )

    item.refresh_from_db()
    assert response.status_code == 302
    assert (item.status, item.outcome) == (Status.RESOLVED, Outcome.LESSON)


def test_resolve_page_rejects_a_missing_outcome(client, item, manager):
    client.force_login(manager)

    response = client.post(resolve_url(item), {"status": "resolved", "outcome": ""})

    item.refresh_from_db()
    assert response.status_code == 200
    assert item.status == Status.NEW
    assert b"Choose what came of it" in response.content


def test_submitter_cannot_resolve_their_own_feedback(client, item, alice):
    client.force_login(alice)

    response = client.post(
        resolve_url(item), {"status": "resolved", "outcome": "nothing"}
    )

    assert response.status_code == 403


def test_submitter_does_not_see_the_resolution_controls(client, item, alice):
    client.force_login(alice)

    response = client.get(reverse("feedback:detail", args=[item.pk]))

    assert b"Resolution" not in response.content


# Lessons

LESSON = {
    "title": "Save the plan before leaving",
    "area": Area.PLANS,
    "what_happened": "Plans were lost",
    "why_it_happens": "",
    "what_to_teach": "Press save",
}


@pytest.fixture
def lesson_item(item, manager):
    set_resolution(item, manager, Status.RESOLVED, Outcome.LESSON)
    return item


def test_new_lesson_is_prefilled_from_the_feedback(client, lesson_item, manager):
    client.force_login(manager)

    response = client.get(reverse("feedback:lesson_new"), {"feedback": lesson_item.pk})

    form = response.context["form"]
    assert form.initial["title"] == "The task list is slow"
    assert form.initial["area"] == Area.TASKS
    assert form.initial["feedback"] == [lesson_item.pk]


def test_write_a_lesson_from_feedback(client, lesson_item, manager):
    client.force_login(manager)

    response = client.post(
        reverse("feedback:lesson_new"), {**LESSON, "feedback": [lesson_item.pk]}
    )

    lesson = Lesson.objects.get()
    assert response.url == reverse("feedback:lesson", args=[lesson.pk])
    assert lesson.created_by == manager
    assert list(lesson.feedback.all()) == [lesson_item]


def test_feedback_linked_to_a_lesson_gets_the_lesson_outcome(client, item, manager):
    client.force_login(manager)

    client.post(
        reverse("feedback:lesson_new") + f"?feedback={item.pk}",
        {**LESSON, "feedback": [item.pk]},
    )

    item.refresh_from_db()
    assert item.outcome == Outcome.LESSON


def test_lesson_needs_what_to_teach(client, manager):
    client.force_login(manager)

    response = client.post(
        reverse("feedback:lesson_new"), {**LESSON, "what_to_teach": ""}
    )

    assert response.status_code == 200
    assert not Lesson.objects.exists()


def test_edit_a_lesson(client, manager):
    lesson = Lesson.objects.create(**{**LESSON, "created_by": manager})
    client.force_login(manager)

    client.post(
        reverse("feedback:lesson_edit", args=[lesson.pk]),
        {**LESSON, "what_to_teach": "Press save, then check"},
    )

    lesson.refresh_from_db()
    assert lesson.what_to_teach == "Press save, then check"
    assert lesson.created_by == manager


def test_lessons_are_for_admins_only(client, alice, manager):
    lesson = Lesson.objects.create(**{**LESSON, "created_by": manager})
    client.force_login(alice)

    for url in (
        reverse("feedback:lessons"),
        reverse("feedback:lesson_new"),
        reverse("feedback:lesson", args=[lesson.pk]),
        reverse("feedback:lesson_edit", args=[lesson.pk]),
    ):
        assert client.get(url).status_code == 403


def test_search_and_filter_lessons(manager):
    plans = Lesson.objects.create(**{**LESSON, "created_by": manager})
    chat = Lesson.objects.create(
        **{
            **LESSON,
            "title": "Use channels",
            "area": Area.CHAT,
            "what_to_teach": "Post in the team channel",
            "created_by": manager,
        }
    )

    assert list(search_lessons("channel")) == [chat]
    assert list(search_lessons("press SAVE")) == [plans]
    assert list(search_lessons(area=Area.PLANS)) == [plans]
    assert list(search_lessons("channel", Area.PLANS)) == []


def test_lesson_pages_render(client, lesson_item, manager):
    lesson = Lesson.objects.create(**{**LESSON, "created_by": manager})
    lesson.feedback.add(lesson_item)
    client.force_login(manager)

    listing = client.get(reverse("feedback:lessons"), {"q": "save"})
    detail = client.get(reverse("feedback:lesson", args=[lesson.pk]))
    source = client.get(reverse("feedback:detail", args=[lesson_item.pk]))

    assert lesson.title.encode() in listing.content
    assert b"The task list is slow" in detail.content
    assert lesson.title.encode() in source.content
    assert b"Write a lesson from this" in source.content
