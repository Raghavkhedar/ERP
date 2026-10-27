import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification

from .models import Attachment, Note, RedFlag, Status
from .services import submit

pytestmark = pytest.mark.django_db


def post_flag(client, against, **extra):
    data = {
        "raised_against": against.pk,
        "incident_date": timezone.localdate().isoformat(),
        "incident": "Shouted at a customer.",
        **extra,
    }
    return client.post(reverse("redflags:new"), data)


@pytest.fixture
def flag(alice, bob):
    return submit(alice, bob, timezone.localdate(), "Shouted at a customer.")


def test_superadmin_can_raise_and_sees_a_confirmation(client, boss, bob):
    client.force_login(boss)
    response = post_flag(client, bob)
    assert response.status_code == 302
    assert response.url == reverse("redflags:sent")
    flag = RedFlag.objects.get()
    assert (flag.raised_by, flag.raised_against) == (boss, bob)
    assert flag.raised_on == timezone.localdate()
    assert client.get(response.url).status_code == 200


def test_htmx_submit_returns_the_sent_partial(client, boss, bob):
    client.force_login(boss)
    response = client.post(
        reverse("redflags:new"),
        {
            "raised_against": bob.pk,
            "incident_date": timezone.localdate().isoformat(),
            "incident": "x",
        },
        HTTP_HX_REQUEST="true",
    )
    assert b"Sent" in response.content
    assert b"<html" not in response.content


def test_raised_by_and_date_cannot_be_spoofed(client, boss, bob, manager):
    client.force_login(boss)
    post_flag(client, bob, raised_by=manager.pk, raised_on="2000-01-01")
    flag = RedFlag.objects.get()
    assert flag.raised_by == boss
    assert flag.raised_on == timezone.localdate()


def test_names_are_kept_as_text(flag, bob):
    assert flag.raised_by_name == "alice"
    assert flag.raised_against_name == "bob"


def test_cannot_flag_yourself(client, boss):
    client.force_login(boss)
    response = post_flag(client, boss)
    assert response.status_code == 200
    assert not RedFlag.objects.exists()


def test_cannot_flag_a_leaver(client, boss, bob):
    bob.is_active = False
    bob.save()
    client.force_login(boss)
    post_flag(client, bob)
    assert not RedFlag.objects.exists()


def test_incident_cannot_be_in_the_future(client, boss, bob):
    client.force_login(boss)
    tomorrow = timezone.localdate() + datetime.timedelta(days=1)
    post_flag(client, bob, incident_date=tomorrow.isoformat())
    assert not RedFlag.objects.exists()


def test_blank_incident_is_refused(client, boss, bob):
    client.force_login(boss)
    post_flag(client, bob, incident="   ")
    assert not RedFlag.objects.exists()


def test_database_refuses_a_flag_against_yourself(alice):
    with pytest.raises(IntegrityError):
        submit(alice, alice, timezone.localdate(), "x")


def test_attachments_are_saved(client, boss, bob):
    client.force_login(boss)
    upload = SimpleUploadedFile("proof.pdf", b"%PDF-1.4", "application/pdf")
    post_flag(client, bob, files=upload)
    assert Attachment.objects.get().original_name == "proof.pdf"


@pytest.mark.parametrize("who", ["alice", "bob", "manager", "trainer"])
def test_everyone_but_a_superadmin_gets_404(client, request, flag, who):
    client.force_login(request.getfixturevalue(who))
    file = Attachment.objects.create(
        red_flag=flag,
        file=SimpleUploadedFile("a.pdf", b"x"),
        original_name="a.pdf",
        size=1,
    )
    for name, args in [
        ("list", []),
        ("detail", [flag.pk]),
        ("attachment", [file.pk]),
    ]:
        assert client.get(reverse(f"redflags:{name}", args=args)).status_code == 404
    assert (
        client.post(reverse("redflags:note", args=[flag.pk]), {"body": "x"}).status_code
        == 404
    )
    assert (
        client.post(
            reverse("redflags:status", args=[flag.pk]), {"status": "closed"}
        ).status_code
        == 404
    )
    assert not Note.objects.exists()
    flag.refresh_from_db()
    assert flag.status == Status.OPEN


def test_anonymous_goes_to_login(client, flag):
    response = client.get(reverse("redflags:detail", args=[flag.pk]))
    assert response.status_code == 302
    assert "login" in response.url


def test_superadmin_reads_notes_and_closes(client, boss, flag):
    client.force_login(boss)
    assert (
        b"Shouted at a customer."
        in client.get(reverse("redflags:detail", args=[flag.pk])).content
    )
    assert b"alice" in client.get(reverse("redflags:list")).content
    client.post(
        reverse("redflags:note", args=[flag.pk]), {"body": "Will talk to them."}
    )
    assert Note.objects.get().author == boss
    client.post(reverse("redflags:status", args=[flag.pk]), {"status": "closed"})
    flag.refresh_from_db()
    assert flag.status == Status.CLOSED
    assert b"alice" not in client.get(reverse("redflags:list")).content


def test_superadmin_downloads_attachments(client, boss, flag):
    file = Attachment.objects.create(
        red_flag=flag,
        file=SimpleUploadedFile("a.pdf", b"data"),
        original_name="a.pdf",
        size=4,
    )
    client.force_login(boss)
    response = client.get(reverse("redflags:attachment", args=[file.pk]))
    assert b"".join(response.streaming_content) == b"data"


def test_only_superadmins_are_notified_without_details(
    alice, bob, boss, manager, trainer
):
    other_boss = boss.__class__.objects.create_user(
        username="boss2", password="pw", is_superuser=True
    )
    submit(alice, bob, timezone.localdate(), "Secret details about bob")
    assert {n.user for n in Notification.objects.all()} == {boss, other_boss}
    for n in Notification.objects.all():
        assert "bob" not in n.text and "Secret" not in n.text and "alice" not in n.text


def test_a_superadmin_raising_a_flag_is_not_notified(boss, bob):
    submit(boss, bob, timezone.localdate(), "x")
    assert not Notification.objects.exists()


def test_inactive_superadmin_is_not_notified(alice, bob, boss):
    boss.is_active = False
    boss.save()
    submit(alice, bob, timezone.localdate(), "x")
    assert not Notification.objects.exists()


def test_menu_shows_red_flags_to_superadmins(client, boss):
    client.force_login(boss)
    page = client.get(reverse("home")).content
    assert b"Raise a red flag" in page
    assert f'href="{reverse("redflags:list")}"'.encode() in page


def test_admin_is_hidden_from_non_superusers(client, manager):
    manager.is_staff = True
    manager.save()
    client.force_login(manager)
    assert client.get("/admin/redflags/redflag/").status_code in (403, 404)


@pytest.mark.parametrize("who", ["alice", "manager", "trainer"])
def test_others_cannot_open_or_submit_the_form(client, request, bob, who):
    client.force_login(request.getfixturevalue(who))
    assert client.get(reverse("redflags:new")).status_code == 404
    assert post_flag(client, bob).status_code == 404
    assert client.get(reverse("redflags:sent")).status_code == 404
    assert not RedFlag.objects.exists()


@pytest.mark.parametrize("who", ["alice", "manager", "trainer"])
def test_others_see_no_red_flag_menu_or_dialog(client, request, who):
    client.force_login(request.getfixturevalue(who))
    page = client.get(reverse("home")).content
    assert b"red flag" not in page.lower()
    assert b"redflag" not in page.lower()
