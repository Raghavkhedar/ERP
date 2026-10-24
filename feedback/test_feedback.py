import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from notifications.models import Notification
from tasks.forms import MAX_FILE_SIZE

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


# Trainers


def test_trainers_are_told_and_can_read_everything(alice, trainer, manager):
    item = submit(alice, Kind.PROBLEM, Area.CHAT, "Lost a message")

    assert len(texts(trainer)) == 1
    assert list(visible_feedback(trainer)) == [item]


def test_trainer_can_reply_resolve_and_write_lessons(client, item, alice, trainer):
    client.force_login(trainer)

    client.post(reverse("feedback:comment", args=[item.pk]), {"body": "Noted"})
    client.post(resolve_url(item), {"status": "resolved", "outcome": "lesson"})
    response = client.post(
        reverse("feedback:lesson_new"), {**LESSON, "feedback": [item.pk]}
    )

    item.refresh_from_db()
    assert item.status == Status.RESOLVED
    assert Lesson.objects.get().created_by == trainer
    assert response.status_code == 302
    assert len(texts(alice)) == 2


def test_trainer_sees_the_lessons_tab(client, item, trainer, alice):
    client.force_login(trainer)
    assert b"Lessons" in client.get(reverse("feedback:list")).content

    client.force_login(alice)
    assert b">Lessons<" not in client.get(reverse("feedback:list")).content


def test_someone_who_is_both_admin_and_trainer_is_told_once(alice, manager):
    manager.groups.add(Group.objects.get(name="Trainer"))

    submit(alice, Kind.PROBLEM, Area.TASKS, "Broken")

    assert len(texts(manager)) == 1


def test_a_removed_trainer_loses_access(client, item, trainer):
    trainer.groups.remove(Group.objects.get(name="Trainer"))
    client.force_login(trainer)

    assert client.get(reverse("feedback:detail", args=[item.pk])).status_code == 404
    assert client.get(reverse("feedback:lessons")).status_code == 403


# Edge cases: who is told


def test_inactive_readers_are_not_told(alice, manager):
    manager.is_active = False
    manager.save()

    submit(alice, Kind.PROBLEM, Area.TASKS, "Broken")

    assert texts(manager) == []


def test_resolving_your_own_feedback_does_not_notify_you(manager):
    own = submit(manager, Kind.PROBLEM, Area.TASKS, "Mine")

    set_resolution(own, manager, Status.RESOLVED, Outcome.NOTHING)

    assert texts(manager) == []


def test_reopening_and_resolving_again_does_not_repeat_the_notice(item, alice, manager):
    set_resolution(item, manager, Status.RESOLVED, Outcome.NOTHING)
    set_resolution(item, manager, Status.DISCUSSING, Outcome.NOTHING)
    item.refresh_from_db()
    assert item.outcome == Outcome.NOTHING

    set_resolution(item, manager, Status.RESOLVED, Outcome.SOFTWARE_FIX)
    assert len(texts(alice)) == 2


def test_replying_on_resolved_feedback_keeps_it_resolved(item, alice, manager):
    set_resolution(item, manager, Status.RESOLVED, Outcome.NOTHING)

    add_comment(item, alice, "One more thing")

    item.refresh_from_db()
    assert item.status == Status.RESOLVED


def test_service_rejects_made_up_status_and_outcome(item, manager):
    with pytest.raises(FeedbackError):
        set_resolution(item, manager, "banana", "")
    with pytest.raises(FeedbackError):
        set_resolution(item, manager, Status.RESOLVED, "banana")


def test_the_database_refuses_resolved_without_an_outcome(item):
    from django.db import IntegrityError, transaction

    item.status = Status.RESOLVED
    with pytest.raises(IntegrityError), transaction.atomic():
        item.save()


# Edge cases: the form


def send(client, **fields):
    data = {"kind": Kind.PROBLEM, "area": Area.TASKS, "message": "Broken", **fields}
    return client.post(NEW_URL, data, headers=HTMX)


def test_unknown_kind_or_area_is_rejected(client, alice):
    client.force_login(alice)

    send(client, kind="rant")
    send(client, area="payroll")

    assert not Feedback.objects.exists()


def test_kind_and_area_are_required(client, alice):
    client.force_login(alice)

    response = send(client, kind="", area="")

    assert response.status_code == 200
    assert b"Choose what kind" in response.content
    assert b"Choose what it is about" in response.content
    assert not Feedback.objects.exists()


def test_message_is_trimmed_and_too_long_is_rejected(client, alice):
    client.force_login(alice)

    send(client, message="  hello  ")
    send(client, message="x" * 4001)

    assert [f.message for f in Feedback.objects.all()] == ["hello"]


@pytest.mark.parametrize(
    "page", ["https://evil.example/", "//evil.example/", "javascript:alert(1)"]
)
def test_unsafe_page_urls_are_dropped(client, alice, page):
    client.force_login(alice)

    send(client, page=page)

    assert Feedback.objects.get().page_url == ""


def test_a_very_long_page_url_is_cut_to_fit(alice):
    item = submit(alice, Kind.PROBLEM, Area.TASKS, "Broken", "/tasks/?x=" + "a" * 500)

    assert len(item.page_url) == 300


@pytest.mark.parametrize(
    ("page", "area"),
    [
        ("/tasks/3/", "tasks"),
        ("/chat/", "chat"),
        ("/meetings/", "meetings"),
        ("/tasks/?person=2", "tasks"),
        ("/", "other"),
        ("/no/such/page/", "other"),
        ("/feedback/", "other"),
    ],
)
def test_area_is_guessed_from_the_page(client, alice, page, area):
    client.force_login(alice)

    response = client.get(NEW_URL, {"page": page}, headers=HTMX)

    assert response.context["form"].initial.get("area", "other") == area


def test_the_form_works_without_javascript(client, alice):
    client.force_login(alice)

    page = client.get(NEW_URL)
    response = client.post(
        NEW_URL, {"kind": Kind.PROBLEM, "area": Area.TASKS, "message": "No JS"}
    )

    assert b"<html" in page.content
    assert response.status_code == 302


# Edge cases: files


def test_a_disallowed_file_type_is_rejected(client, alice):
    client.force_login(alice)

    response = send(
        client, files=SimpleUploadedFile("run.exe", b"MZ", content_type="x/y")
    )

    assert response.status_code == 200
    assert b"can&#x27;t be attached" in response.content
    assert not Feedback.objects.exists()


def test_a_file_over_the_limit_is_rejected(client, alice):
    client.force_login(alice)
    big = SimpleUploadedFile("big.pdf", b"0" * (MAX_FILE_SIZE + 1))

    response = send(client, files=big)

    assert response.status_code == 200
    assert not Feedback.objects.exists()
    assert not Attachment.objects.exists()


def test_too_many_files_are_rejected(client, alice):
    client.force_login(alice)
    files = [screenshot(f"s{i}.png") for i in range(11)]

    send(client, files=files)

    assert not Feedback.objects.exists()


def test_several_files_are_kept_and_named_safely(alice):
    item = submit(
        alice,
        Kind.PROBLEM,
        Area.TASKS,
        "Broken",
        files=[screenshot("a.png"), screenshot("../../etc/passwd.png")],
    )

    stored = list(item.attachments.all())
    assert len(stored) == 2
    assert all(f.file.name.startswith("feedback/") for f in stored)
    assert all(".." not in f.file.name for f in stored)


def test_attachment_that_does_not_exist_is_404(client, alice):
    client.force_login(alice)

    assert client.get(reverse("feedback:attachment", args=[999])).status_code == 404


# Edge cases: replies and lists


def test_blank_reply_is_rejected(client, item, manager):
    client.force_login(manager)

    response = client.post(reverse("feedback:comment", args=[item.pk]), {"body": "  "})

    assert response.status_code == 200
    assert not item.comments.exists()
    assert b"Write a message" in response.content


def test_replying_needs_post(client, item, manager):
    client.force_login(manager)

    response = client.get(reverse("feedback:comment", args=[item.pk]))

    assert response.status_code == 405


def test_a_stranger_cannot_reply_through_the_page(client, item, bob):
    client.force_login(bob)

    response = client.post(reverse("feedback:comment", args=[item.pk]), {"body": "Hi"})

    assert response.status_code == 404
    assert not item.comments.exists()


def test_filters_on_the_list(client, item, alice, manager):
    done = submit(alice, Kind.PRAISE, Area.CHAT, "Great chat")
    set_resolution(done, manager, Status.RESOLVED, Outcome.NOTHING)
    client.force_login(manager)

    def shown(show):
        response = client.get(reverse("feedback:list"), {"show": show})
        return set(response.context["items"])

    assert shown("open") == {item}
    assert shown("resolved") == {done}
    assert shown("all") == {item, done}
    assert shown("nonsense") == {item, done}
    assert set(client.get(reverse("feedback:list")).context["items"]) == {item}


def test_a_former_employees_feedback_is_anonymised(client, item, alice, manager):
    alice.is_active = False
    alice.save()
    client.force_login(manager)

    page = client.get(reverse("feedback:detail", args=[item.pk]))

    assert b"Former employee" in page.content
    assert b"alice" not in page.content.lower().replace(b"slice", b"")


@pytest.mark.parametrize("url_name", ["list", "new", "lessons", "lesson_new"])
def test_every_page_needs_login(client, url_name):
    assert client.get(reverse(f"feedback:{url_name}")).status_code == 302


# Edge cases: lessons


def test_lesson_pages_for_unknown_ids_are_404(client, manager):
    client.force_login(manager)

    assert client.get(reverse("feedback:lesson", args=[999])).status_code == 404
    assert client.get(reverse("feedback:lesson_edit", args=[999])).status_code == 404


@pytest.mark.parametrize("wanted", ["999", "abc", "", "-1"])
def test_a_bad_feedback_parameter_gives_an_empty_lesson_form(client, manager, wanted):
    client.force_login(manager)

    response = client.get(reverse("feedback:lesson_new"), {"feedback": wanted})

    assert response.status_code == 200
    assert not response.context["form"].initial


def test_a_lesson_can_only_link_feedback_meant_for_lessons(client, item, manager):
    client.force_login(manager)

    response = client.post(
        reverse("feedback:lesson_new"), {**LESSON, "feedback": [item.pk]}
    )

    assert response.status_code == 200
    assert not Lesson.objects.exists()


def test_a_lesson_without_source_feedback_is_allowed(client, manager):
    client.force_login(manager)

    client.post(reverse("feedback:lesson_new"), LESSON)

    assert Lesson.objects.get().feedback.count() == 0


def test_editing_a_lesson_keeps_its_links_and_author(
    client, lesson_item, manager, trainer
):
    lesson = Lesson.objects.create(**{**LESSON, "created_by": manager})
    lesson.feedback.add(lesson_item)
    client.force_login(trainer)

    client.post(
        reverse("feedback:lesson_edit", args=[lesson.pk]),
        {**LESSON, "title": "New title", "feedback": [lesson_item.pk]},
    )

    lesson.refresh_from_db()
    assert lesson.title == "New title"
    assert lesson.created_by == manager
    assert list(lesson.feedback.all()) == [lesson_item]


def test_unlinking_feedback_from_a_lesson(client, lesson_item, manager):
    lesson = Lesson.objects.create(**{**LESSON, "created_by": manager})
    lesson.feedback.add(lesson_item)
    client.force_login(manager)

    client.post(reverse("feedback:lesson_edit", args=[lesson.pk]), LESSON)

    assert lesson.feedback.count() == 0


def test_blank_title_or_module_is_rejected(client, manager):
    client.force_login(manager)

    client.post(reverse("feedback:lesson_new"), {**LESSON, "title": " "})
    client.post(reverse("feedback:lesson_new"), {**LESSON, "area": ""})
    client.post(reverse("feedback:lesson_new"), {**LESSON, "area": "payroll"})

    assert not Lesson.objects.exists()


def test_search_ignores_blank_and_unknown_filters(client, manager):
    Lesson.objects.create(**{**LESSON, "created_by": manager})
    client.force_login(manager)

    for params in ({"q": "   "}, {"area": "payroll"}, {"q": "%", "area": ""}):
        response = client.get(reverse("feedback:lessons"), params)
        assert response.status_code == 200

    assert (
        len(client.get(reverse("feedback:lessons"), {"q": "   "}).context["lessons"])
        == 1
    )
    assert (
        len(
            client.get(reverse("feedback:lessons"), {"area": "payroll"}).context[
                "lessons"
            ]
        )
        == 1
    )


def test_search_needs_every_word(manager):
    Lesson.objects.create(**{**LESSON, "created_by": manager})

    assert search_lessons("plans lost")
    assert not search_lessons("plans banana")


def test_lessons_are_listed_under_their_module(client, manager):
    Lesson.objects.create(**{**LESSON, "created_by": manager})
    Lesson.objects.create(
        **{**LESSON, "title": "Another", "area": Area.CHAT, "created_by": manager}
    )
    client.force_login(manager)

    page = client.get(reverse("feedback:lessons")).content.decode()

    assert page.index("Another") < page.index("Save the plan before leaving")
    assert ">Chat<" in page
    assert ">Daily plan<" in page


# The top bar


def test_the_top_bar_has_a_single_feedback_control(client, alice):
    client.force_login(alice)

    page = client.get(reverse("home")).content

    assert page.count(b">Feedback<") == 1
    assert b"Give feedback" in page
    assert b"Your feedback" in page
    assert b"Lessons" not in page


def test_readers_get_inbox_and_lessons_in_the_same_menu(client, trainer):
    client.force_login(trainer)

    page = client.get(reverse("home")).content

    assert page.count(b">Feedback<") == 1
    assert b"Feedback inbox" in page
    assert reverse("feedback:lessons").encode() in page
