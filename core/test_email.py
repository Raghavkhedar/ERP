import re

import pytest
from django.core import mail
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from chat.services import post_notice

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="S10", first_name="Alice", email="alice@senken.test", password="pw"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="S11", first_name="Bob", email="bob@senken.test", password="pw"
    )


# Notices


def test_a_notice_is_emailed_to_the_recipient(
    alice, bob, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        post_notice(bob, alice, "assigned you a task (P1, due Fri 30 Oct): Audit")

    [email] = mail.outbox
    assert email.to == ["alice@senken.test"]
    assert email.subject == (
        "Senken ERP: Bob assigned you a task (P1, due Fri 30 Oct): Audit"
    )
    assert "http://localhost:8000/chat/" in email.body


def test_no_email_without_an_address_or_for_leavers(
    alice, bob, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        bob.email = ""
        bob.save()
        post_notice(alice, bob, "booked your slot")
        alice.is_active = False
        alice.save()
        post_notice(bob, alice, "cancelled your booking")

    assert mail.outbox == []


def test_a_mail_outage_does_not_break_the_notice(
    alice, bob, django_capture_on_commit_callbacks, monkeypatch
):
    def boom(*args, **kwargs):
        raise OSError("SMTP is down")

    monkeypatch.setattr("chat.services.send_mail", boom)

    with django_capture_on_commit_callbacks(execute=True):
        message = post_notice(bob, alice, "closed your task")

    assert message.pk  # the chat notice is still there


# Forgot password


def test_the_login_page_links_to_forgot_password(client):
    assert reverse("password_reset") in client.get(reverse("login")).content.decode()


def test_a_reset_link_is_emailed_and_works_once(client, alice):
    response = client.post(reverse("password_reset"), {"email": "ALICE@senken.test"})

    assert response.status_code == 302
    [email] = mail.outbox
    assert email.to == ["alice@senken.test"]
    link = re.search(r"https?://\S+", email.body).group(0)
    path = "/" + link.split("/", 3)[3]
    page = client.get(path, follow=True)  # Django swaps the token for a session
    form_url = page.redirect_chain[-1][0]

    response = client.post(
        form_url,
        {"new_password1": "a-fresh-pass-8841", "new_password2": "a-fresh-pass-8841"},
    )

    assert response.status_code == 302
    alice.refresh_from_db()
    assert alice.check_password("a-fresh-pass-8841")
    assert not alice.must_change_password
    assert "Link expired" in client.get(path, follow=True).content.decode()


def test_unknown_emails_get_the_same_answer_and_no_mail(client, alice):
    response = client.post(reverse("password_reset"), {"email": "nobody@senken.test"})

    assert response.status_code == 302
    assert response.url == reverse("password_reset_done")
    assert mail.outbox == []


def test_leavers_cannot_reset(client, alice):
    alice.is_active = False
    alice.save()  # clears the email too, but the check must not rely on that

    client.post(reverse("password_reset"), {"email": "alice@senken.test"})

    assert mail.outbox == []


def test_a_bad_token_shows_the_expired_page(client, alice):
    uid = urlsafe_base64_encode(force_bytes(alice.pk))
    response = client.get(
        reverse("password_reset_confirm", args=[uid, "bad-token"]), follow=True
    )
    assert "Link expired" in response.content.decode()
