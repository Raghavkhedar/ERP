from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.access import companies_with_access, require_section
from hiring.forms import ScheduleCallForm
from hiring.services import stage, timeline

from .export import people_workbook
from .forms import PersonForm
from .models import Person
from .services import StaleCard, archive, card_rows, save_person, visible_people

section = require_section("recruitment", "people")


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


def _has_hr(request):
    return (
        companies_with_access(request.user, "recruitment", "assessments")
        .filter(pk__in=[c.pk for c in request.companies])
        .exists()
    )


@section
def person_detail(request, pk):
    person = _card(request, pk)
    return render(
        request,
        "people/detail.html",
        {
            "person": person,
            "rows": card_rows(person),
            "same_number": person.same_number(),
            "stage": stage(person),
            "schedule_form": ScheduleCallForm(),
            "events": timeline(person, with_hr=_has_hr(request)),
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
