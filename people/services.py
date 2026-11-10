from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Person


class StaleCard(Exception):
    """Someone saved the card after this form was opened."""


def card_rows(person):
    """The labelled facts the candidate card shows."""
    return [
        ("Phone", person.phone),
        ("Email", person.email),
        ("Gender", person.get_gender_display()),
        ("Address", person.address),
        ("Current employer", person.current_employer),
        ("Current salary", person.current_salary),
        ("Expected salary", person.expected_salary),
        ("Experience (years)", person.experience_years),
        ("Joining period", person.joining_period),
        ("Contact status", person.get_contact_status_display()),
        ("Priority", person.get_priority_display()),
    ]


def visible_people(companies, search="", status=""):
    people = Person.objects.filter(company__in=companies, archived_at__isnull=True)
    if status:
        people = people.filter(contact_status=status)
    for word in search.split():
        people = people.filter(
            Q(name__icontains=word)
            | Q(phone__icontains=word)
            | Q(phone_key__icontains=word)
            | Q(email__icontains=word)
        )
    return people


def save_person(form, version=None):
    """Save a card from a valid form. For an existing card, `version` must be the
    one the form was opened at; otherwise nothing is saved."""
    with transaction.atomic():
        if form.instance.pk:
            current = Person.objects.select_for_update().get(pk=form.instance.pk)
            if version != current.version:
                raise StaleCard
            form.instance.version = current.version + 1
        return form.save()


def archive(person):
    # Cards are archived, never deleted: calls and interviews will point at them.
    person.archived_at = timezone.now()
    person.version += 1
    person.save(update_fields=["archived_at", "version"])
