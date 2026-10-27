import pytest
from django.contrib.admin.sites import site
from django.db import IntegrityError, transaction
from django.test import RequestFactory
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_superuser(
        username="boss", first_name="boss", password="pw"
    )


@pytest.fixture
def supervisor(django_user_model):
    return django_user_model.objects.create_user(
        username="S1", first_name="sam", password="pw"
    )


@pytest.fixture
def employee(django_user_model):
    return django_user_model.objects.create_user(
        username="S2", first_name="emma", password="pw"
    )


def test_supervisor_is_optional_and_lists_reports(supervisor, employee):
    assert employee.supervisor is None
    employee.supervisor = supervisor
    employee.save()
    assert list(supervisor.reports.all()) == [employee]


def test_nobody_is_their_own_supervisor(employee):
    employee.supervisor = employee
    with pytest.raises(IntegrityError), transaction.atomic():
        employee.save()


def test_leaving_supervisor_clears_the_link(supervisor, employee):
    employee.supervisor = supervisor
    employee.save()
    supervisor.delete()
    employee.refresh_from_db()
    assert employee.supervisor is None


def test_admin_form_saves_supervisor(boss, supervisor, employee):
    request = RequestFactory().get("/")
    request.user = boss
    model_admin = site.get_model_admin(type(employee))
    form_class = model_admin.get_form(request, employee, fields=["supervisor"])
    form = form_class({"supervisor": supervisor.pk}, instance=employee)
    assert form.is_valid(), form.errors
    form.save()
    employee.refresh_from_db()
    assert employee.supervisor == supervisor


def test_admin_change_page_shows_supervisor(client, boss, employee):
    client.force_login(boss)
    response = client.get(reverse("admin:core_user_change", args=[employee.pk]))
    assert "supervisor" in response.context["adminform"].form.fields


def test_admin_offers_only_active_people_as_supervisor(
    boss, supervisor, employee, django_user_model
):
    leaver = django_user_model.objects.create_user(
        username="S3", first_name="lee", password="pw", is_active=False
    )
    request = RequestFactory().get("/")
    request.user = boss
    model_admin = site.get_model_admin(type(employee))
    field = model_admin.get_form(request, employee).base_fields["supervisor"]
    assert supervisor in field.queryset
    assert leaver not in field.queryset
