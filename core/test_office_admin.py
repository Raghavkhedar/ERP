import pytest
from django.contrib.admin.sites import site
from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.urls import reverse

pytestmark = pytest.mark.django_db

PRIVILEGE_FIELDS = {"is_staff", "is_superuser", "groups", "user_permissions"}


@pytest.fixture
def office_admin(django_user_model):
    user = django_user_model.objects.create_user(
        username="manager", first_name="manager", password="pw", is_staff=True
    )
    user.groups.add(Group.objects.get(name="Office admin"))
    return user


@pytest.fixture
def employee(django_user_model):
    return django_user_model.objects.create_user(
        username="employee", first_name="employee", password="pw"
    )


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_superuser(
        username="boss", first_name="boss", password="pw"
    )


def user_form_fields(acting_user, obj):
    request = RequestFactory().get("/")
    request.user = acting_user
    model_admin = site.get_model_admin(type(obj))
    return set(model_admin.get_form(request, obj).base_fields)


def test_office_admin_group_has_exactly_the_planned_permissions():
    group = Group.objects.get(name="Office admin")
    assert set(group.permissions.values_list("codename", flat=True)) == {
        "add_user",
        "change_user",
        "view_user",
        "add_conversation",
        "change_conversation",
        "view_conversation",
        "add_membership",
        "change_membership",
        "delete_membership",
        "view_membership",
    }


def test_office_admin_can_add_people(client, office_admin):
    client.force_login(office_admin)
    assert client.get(reverse("admin:core_user_add")).status_code == 200


def test_office_admin_form_has_no_privilege_fields(office_admin, employee):
    fields = user_form_fields(office_admin, employee)
    assert not fields & PRIVILEGE_FIELDS
    assert "is_active" in fields


def test_superuser_form_keeps_privilege_fields(boss, employee):
    assert PRIVILEGE_FIELDS <= user_form_fields(boss, employee)


def test_office_admin_user_list_hides_privileged_accounts(
    client, office_admin, employee, boss
):
    client.force_login(office_admin)
    html = client.get(reverse("admin:core_user_changelist")).content.decode()
    assert "employee" in html
    assert "boss" not in html


def test_office_admin_cannot_open_superuser_account(client, office_admin, boss):
    client.force_login(office_admin)
    response = client.get(reverse("admin:core_user_change", args=[boss.pk]))
    assert response.status_code == 302


def test_office_admin_cannot_reset_superuser_password(client, office_admin, boss):
    client.force_login(office_admin)
    url = reverse("admin:auth_user_password_change", args=[boss.pk])
    assert client.get(url).status_code == 404


def test_office_admin_cannot_delete_people(client, office_admin, employee):
    client.force_login(office_admin)
    url = reverse("admin:core_user_delete", args=[employee.pk])
    assert client.get(url).status_code == 403


def test_office_admin_can_manage_channels(client, office_admin):
    client.force_login(office_admin)
    assert client.get(reverse("admin:chat_conversation_add")).status_code == 200


def test_office_admin_cannot_read_messages(client, office_admin):
    client.force_login(office_admin)
    response = client.get(reverse("admin:chat_message_changelist"))
    assert response.status_code == 403


def test_ordinary_user_cannot_open_admin(client, employee):
    client.force_login(employee)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302


def test_trainer_group_exists_without_permissions():
    group = Group.objects.get(name="Trainer")
    assert group.permissions.count() == 0


def test_is_trainer_follows_the_group(employee):
    assert not employee.is_trainer
    employee.groups.add(Group.objects.get(name="Trainer"))
    assert employee.is_trainer
    assert not employee.is_office_admin


def test_office_admin_cannot_hand_out_the_trainer_group(office_admin, employee):
    # Groups are a privilege field: only a superuser can put someone in one.
    assert "groups" not in user_form_fields(office_admin, employee)
