import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification

from .models import Attachment, Note, Status
from .services import RedFlagError, add_note, assign_to_supervisor, set_status, submit

pytestmark = pytest.mark.django_db


@pytest.fixture
def lead_a(django_user_model):
    return django_user_model.objects.create_user(
        username="lead_a", first_name="lead_a", password="pw"
    )


@pytest.fixture
def lead_b(django_user_model):
    return django_user_model.objects.create_user(
        username="lead_b", first_name="lead_b", password="pw"
    )


@pytest.fixture
def flag(alice, bob, lead_a, lead_b):
    # alice raises against bob; each has a different supervisor.
    alice.supervisor = lead_a
    alice.save()
    bob.supervisor = lead_b
    bob.save()
    return submit(alice, bob, timezone.localdate(), "Shouted at a customer.")


@pytest.fixture
def other_flag(boss, bob):
    return submit(boss, bob, timezone.localdate(), "Late again.")


def test_assign_against_picks_the_supervisor_of_the_accused(flag, boss, lead_b):
    assign_to_supervisor(flag, boss, "against")
    flag.refresh_from_db()
    assert flag.assigned_to == lead_b
    assert flag.assigned_on == timezone.localdate()


def test_assign_raiser_picks_the_supervisor_of_the_raiser(flag, boss, lead_a):
    assign_to_supervisor(flag, boss, "raiser")
    flag.refresh_from_db()
    assert flag.assigned_to == lead_a


def test_supervisor_is_notified_without_details(flag, boss, lead_b):
    assign_to_supervisor(flag, boss, "against")
    note = Notification.objects.get(user=lead_b)
    assert note.url == reverse("redflags:detail", args=[flag.pk])
    assert "Shouted" not in note.text and "bob" not in note.text


def test_no_supervisor_is_a_clear_error(alice, bob, boss):
    flag = submit(alice, bob, timezone.localdate(), "x")
    with pytest.raises(RedFlagError, match="no supervisor"):
        assign_to_supervisor(flag, boss, "against")
    flag.refresh_from_db()
    assert flag.assigned_to is None


def test_a_leaver_cannot_be_assigned(flag, boss, lead_b):
    lead_b.is_active = False
    lead_b.save()
    with pytest.raises(RedFlagError):
        assign_to_supervisor(flag, boss, "against")


@pytest.mark.parametrize("who", ["alice", "manager", "trainer", "lead_a"])
def test_only_superadmins_assign(flag, request, who):
    with pytest.raises(PermissionDenied):
        assign_to_supervisor(flag, request.getfixturevalue(who), "against")


def test_supervisor_reads_only_the_assigned_flag(
    client, flag, other_flag, boss, lead_b
):
    assign_to_supervisor(flag, boss, "against")
    client.force_login(lead_b)
    assert client.get(reverse("redflags:detail", args=[flag.pk])).status_code == 200
    other = reverse("redflags:detail", args=[other_flag.pk])
    assert client.get(other).status_code == 404
    listing = client.get(reverse("redflags:list")).content
    assert b"Shouted at a customer." in listing
    assert b"Late again." not in listing


def test_supervisor_downloads_assigned_attachments_only(
    client, flag, other_flag, boss, lead_b
):
    assign_to_supervisor(flag, boss, "against")
    mine = Attachment.objects.create(
        red_flag=flag,
        file=SimpleUploadedFile("a.pdf", b"x"),
        original_name="a.pdf",
        size=1,
    )
    theirs = Attachment.objects.create(
        red_flag=other_flag,
        file=SimpleUploadedFile("b.pdf", b"x"),
        original_name="b.pdf",
        size=1,
    )
    client.force_login(lead_b)
    assert client.get(reverse("redflags:attachment", args=[mine.pk])).status_code == 200
    assert (
        client.get(reverse("redflags:attachment", args=[theirs.pk])).status_code == 404
    )


def test_supervisor_adds_notes_but_cannot_change_status_or_assign(
    client, flag, boss, lead_b
):
    assign_to_supervisor(flag, boss, "against")
    client.force_login(lead_b)
    response = client.post(
        reverse("redflags:note", args=[flag.pk]), {"body": "Spoke to them."}
    )
    assert response.status_code == 302
    assert Note.objects.get().author == lead_b
    assert (
        client.post(
            reverse("redflags:status", args=[flag.pk]), {"status": "closed"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("redflags:assign", args=[flag.pk]), {"of": "raiser"}
        ).status_code
        == 404
    )
    assert client.post(reverse("redflags:unassign", args=[flag.pk])).status_code == 404
    flag.refresh_from_db()
    assert flag.status == Status.OPEN
    with pytest.raises(PermissionDenied):
        set_status(flag, lead_b, Status.CLOSED)


def test_supervisor_cannot_note_an_unassigned_flag(flag, other_flag, boss, lead_b):
    assign_to_supervisor(flag, boss, "against")
    with pytest.raises(PermissionDenied):
        add_note(other_flag, lead_b, "hi")


def test_detail_hides_status_and_assign_controls_from_the_supervisor(
    client, flag, boss, lead_b
):
    assign_to_supervisor(flag, boss, "against")
    client.force_login(lead_b)
    html = client.get(reverse("redflags:detail", args=[flag.pk])).content.decode()
    assert reverse("redflags:status", args=[flag.pk]) not in html
    assert reverse("redflags:assign", args=[flag.pk]) not in html
    assert reverse("redflags:note", args=[flag.pk]) in html


def test_superadmin_assigns_and_removes_through_the_pages(client, flag, boss, lead_b):
    client.force_login(boss)
    client.post(reverse("redflags:assign", args=[flag.pk]), {"of": "against"})
    flag.refresh_from_db()
    assert flag.assigned_to == lead_b
    assert (
        "lead_b"
        in client.get(reverse("redflags:detail", args=[flag.pk])).content.decode()
    )
    client.post(reverse("redflags:unassign", args=[flag.pk]))
    flag.refresh_from_db()
    assert flag.assigned_to is None


def test_removing_the_assignment_closes_the_door(client, flag, boss, lead_b):
    assign_to_supervisor(flag, boss, "against")
    client.force_login(boss)
    client.post(reverse("redflags:unassign", args=[flag.pk]))
    client.force_login(lead_b)
    assert client.get(reverse("redflags:detail", args=[flag.pk])).status_code == 404
    assert client.get(reverse("redflags:list")).status_code == 404


def test_menu_shows_red_flags_only_to_supervisors_holding_one(
    client, flag, boss, lead_b
):
    client.force_login(lead_b)
    inbox = f'href="{reverse("redflags:list")}"'
    assert inbox not in client.get("/").content.decode()
    assign_to_supervisor(flag, boss, "against")
    assert inbox in client.get("/").content.decode()
