from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.access import require_section

from .export import people_workbook
from .forms import PersonForm
from .models import Person
from .services import StaleCard, archive, save_person, visible_people

section = require_section("recruitment", "candidates")


def _shown(request):
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    return search, status, visible_people(request.companies, search, status)


def _card(request, pk):
    return get_object_or_404(visible_people(request.companies), pk=pk)


@section
def person_list(request):
    search, status, people = _shown(request)
    return render(
        request,
        "people/list.html",
        {
            "people": people[:200],
            "total": people.count(),
            "search": search,
            "status": status,
            "statuses": Person.ContactStatus.choices,
        },
    )


@section
@require_GET
def export_people(request):
    return people_workbook(_shown(request)[2])


@section
def person_detail(request, pk):
    person = _card(request, pk)
    return render(
        request,
        "people/detail.html",
        {
            "person": person,
            "rows": [
                ("Phone", person.phone),
                ("Email", person.email),
                ("Address", person.address),
                ("Current employer", person.current_employer),
                ("Current salary", person.current_salary),
                ("Expected salary", person.expected_salary),
                ("Experience (years)", person.experience_years),
                ("Joining period", person.joining_period),
                ("Contact status", person.get_contact_status_display()),
                ("Priority", person.get_priority_display()),
            ],
            "same_number": person.same_number().filter(archived_at=None),
        },
    )


@section
def new_person(request):
    form = PersonForm(request.POST or None)
    # shortcut: all-companies view files a new card under the first company,
    # add a company picker if that matters
    company = request.companies[0]
    if request.method == "POST" and form.is_valid():
        form.instance.company = company
        person = save_person(form)
        messages.success(request, f"{person.name} added.")
        return redirect("people:detail", pk=person.pk)
    return render(request, "people/form.html", {"form": form, "person": None})


@section
def edit_person(request, pk):
    person = _card(request, pk)
    form = PersonForm(
        request.POST or None, instance=person, initial={"version": person.version}
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_person(form, form.cleaned_data["version"])
        except StaleCard:
            messages.error(
                request,
                "Someone else changed this card while you were editing. "
                "Your changes were not saved.",
            )
            return redirect("people:edit", pk=pk)
        messages.success(request, "Saved.")
        return redirect("people:detail", pk=pk)
    return render(request, "people/form.html", {"form": form, "person": person})


@section
@require_POST
def archive_person(request, pk):
    archive(_card(request, pk))
    messages.success(request, "Card archived.")
    return redirect("people:list")
