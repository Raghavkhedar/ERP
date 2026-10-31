from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from core.access import require_section

from .excel import SheetError, import_numbers
from .export import sourced_workbook
from .forms import ImportForm, SourceForm
from .models import Requisition
from .services import (
    source_number,
    sources_in_use,
    visible_requisitions,
    visible_sourced,
)

section = require_section("recruitment", "candidates")


def _open(request):
    return visible_requisitions(request.companies, Requisition.Status.OPEN)


def _shown(request):
    req = request.GET.get("requisition", "")
    dups = request.GET.get("dup") == "1"
    rows = visible_sourced(request.companies, int(req) if req.isdigit() else None, dups)
    return req, dups, rows


@section
def sourcing(request):
    req, dups, rows = _shown(request)
    return render(
        request,
        "hiring/sourcing.html",
        {
            "rows": rows[:200],
            "total": rows.count(),
            "requisition": req,
            "dups": dups,
            "requisitions": visible_requisitions(request.companies),
        },
    )


@section
@require_GET
def export_sourced(request):
    return sourced_workbook(_shown(request)[2])


def _form_page(request, form, title, help_text=""):
    return render(
        request,
        "hiring/source_form.html",
        {
            "form": form,
            "title": title,
            "sources": sources_in_use(request.companies),
            "multipart": "sheet" in form.fields,
            "help": help_text,
        },
    )


@section
def new_source(request):
    form = SourceForm(request.POST or None, requisitions=_open(request))
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        made = source_number(
            d["requisition"],
            d["name"],
            d["phone"],
            request.user,
            d["source"],
            d["email"],
        )
        if made.is_duplicate:
            messages.success(
                request,
                f"Already on file as {made.person.name}: "
                "logged as a duplicate, no new card.",
            )
        else:
            messages.success(request, f"{made.person.name} added.")
        return redirect("hiring:sourcing")
    return _form_page(request, form, "Add a number")


@section
def import_source(request):
    form = ImportForm(
        request.POST or None, request.FILES or None, requisitions=_open(request)
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            new, dups, skipped = import_numbers(
                d["requisition"], d["sheet"], request.user, d["source"]
            )
        except SheetError as exc:
            form.add_error("sheet", str(exc))
        else:
            note = f"{new} new, {dups} duplicate."
            if skipped:
                shown = "; ".join(f"row {n}: {why}" for n, why in skipped[:5])
                more = "…" if len(skipped) > 5 else ""
                note += f" Skipped {len(skipped)} ({shown}{more})."
            messages.success(request, note)
            return redirect("hiring:sourcing")
    return _form_page(
        request,
        form,
        "Import from Excel",
        "The first row needs Name and Phone headings. "
        "Email and Source columns are optional.",
    )
