from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from .forms import MAX_FILE_SIZE
from .models import Attachment, Status, TaskUpdate
from .services import TaskError, add_update, assign, set_status
from .timeline import DAYS_BEFORE_TODAY, build

pytestmark = pytest.mark.django_db

NEW_URL = reverse("tasks:update_new")
HTMX = {"HX-Request": "true"}
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01"
    b"\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def screenshot(name="screenshot.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


def attachment_url(file):
    return reverse("tasks:attachment", args=[file.pk])


# Service


def test_logging_an_update_with_files(task, alice, tmp_path):
    update = add_update(task, alice, "  Collected the bank statements ", [screenshot()])

    assert update.body == "Collected the bank statements"
    [file] = update.attachments.all()
    assert file.original_name == "screenshot.png"
    assert file.size == len(PNG)
    assert file.is_image
    assert file.file.name.startswith("tasks/")
    assert "screenshot" not in file.file.name  # stored under a random name
    assert (tmp_path / file.file.name).read_bytes() == PNG


def test_the_first_update_starts_the_task(task, alice):
    add_update(task, alice, "Started")

    task.refresh_from_db()
    assert task.status == Status.ONGOING


def test_an_admins_note_does_not_start_it(task, boss):
    add_update(task, boss, "Remember the GST filings")

    task.refresh_from_db()
    assert task.status == Status.OPEN


def test_others_cannot_log_on_your_task(task, bob):
    with pytest.raises(PermissionDenied):
        add_update(task, bob, "Done it")


def test_closed_tasks_take_no_updates(task, boss, alice):
    set_status(task, boss, Status.CLOSED)

    with pytest.raises(TaskError):
        add_update(task, alice, "One more thing")


# Form


def test_adding_from_the_dialog(client, task, alice):
    client.force_login(alice)
    data = {
        "task": task.pk,
        "body": "Collected statements",
        "files": [screenshot(), SimpleUploadedFile("notes.pdf", b"%PDF-1.4")],
        "next": "/",
    }

    response = client.post(NEW_URL, data, headers=HTMX)

    assert response["HX-Redirect"] == "/"
    update = TaskUpdate.objects.get()
    assert [f.original_name for f in update.attachments.all()] == [
        "screenshot.png",
        "notes.pdf",
    ]


def test_the_task_list_offers_only_open_own_tasks(
    client, task, boss, alice, bob, next_week
):
    assign(boss, bob, 1, "Bob's job", next_week)
    closed = assign(boss, alice, 2, "Old job", next_week)
    set_status(closed, boss, Status.CLOSED)
    client.force_login(alice)

    response = client.get(NEW_URL, headers=HTMX)

    assert list(response.context["form"].fields["task"].queryset) == [task]


def test_someone_elses_task_is_refused(client, task, bob):
    client.force_login(bob)

    client.post(NEW_URL, {"task": task.pk, "body": "Mine now"}, headers=HTMX)

    assert not TaskUpdate.objects.exists()


def test_files_over_10_mb_are_refused(client, task, alice):
    client.force_login(alice)
    big = SimpleUploadedFile("scan.pdf", b"0" * (MAX_FILE_SIZE + 1))

    response = client.post(
        NEW_URL, {"task": task.pk, "body": "Scan", "files": [big]}, headers=HTMX
    )

    assert b"Files can be up to 10.0" in response.content
    assert not TaskUpdate.objects.exists()


@pytest.mark.parametrize("name", ["run.exe", "page.html", "drawing.svg", "noext"])
def test_other_file_types_are_refused(client, task, alice, name):
    client.force_login(alice)
    data = {"task": task.pk, "body": "Hi", "files": [SimpleUploadedFile(name, b"x")]}

    response = client.post(NEW_URL, data, headers=HTMX)

    assert b"can&#x27;t be attached" in response.content
    assert not Attachment.objects.exists()


def test_a_blank_update_is_refused(client, task, alice):
    client.force_login(alice)

    client.post(NEW_URL, {"task": task.pk, "body": "   "}, headers=HTMX)

    assert not TaskUpdate.objects.exists()


# Files


def test_the_assignee_and_admins_open_files(client, task, alice, manager):
    update = add_update(task, alice, "Photo", [screenshot()])
    file = update.attachments.get()

    for person in (alice, manager):
        client.force_login(person)
        response = client.get(attachment_url(file))
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == PNG
        assert response["Content-Disposition"].startswith("inline")


def test_documents_download(client, task, alice):
    pdf = SimpleUploadedFile("notes.pdf", b"%PDF-1.4")
    file = add_update(task, alice, "Notes", [pdf]).attachments.get()
    client.force_login(alice)

    response = client.get(attachment_url(file))

    assert response["Content-Disposition"] == 'attachment; filename="notes.pdf"'


def test_outsiders_cannot_open_files(client, task, alice, bob):
    file = add_update(task, alice, "Photo", [screenshot()]).attachments.get()
    client.force_login(bob)

    assert client.get(attachment_url(file)).status_code == 404


# Task page and timeline


def test_the_task_page_lists_updates(client, task, alice):
    add_update(task, alice, "Collected statements", [screenshot()])
    client.force_login(alice)

    response = client.get(reverse("tasks:detail", args=[task.pk]))

    assert b"Collected statements" in response.content
    assert b"screenshot.png" in response.content


def test_updates_show_as_dots_on_the_timeline(task, alice):
    add_update(task, alice, "First")
    add_update(task, alice, "Second")

    [group] = build(alice).groups
    [dot] = group.bars[0].updates
    assert dot.column == DAYS_BEFORE_TODAY + 2
    assert dot.count == 2
    assert dot.update.body == "Second"


def test_old_updates_fall_outside_the_window(task, alice):
    add_update(task, alice, "Long ago")
    TaskUpdate.objects.update(created_at=timezone.now() - timedelta(days=30))

    [group] = build(alice).groups
    assert group.bars[0].updates == []


def test_the_plus_button_shows_for_people_with_open_tasks(client, task, alice, bob):
    client.force_login(alice)
    assert b"Add an update" in client.get(reverse("home")).content

    client.force_login(bob)
    assert b"Add an update" not in client.get(reverse("home")).content
