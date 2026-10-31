from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.access import require_section

from .export import STEPS, funnel_workbook, requisitions_workbook
from .forms import RequisitionForm
from .models import Requisition
from .services import (
    StaleRequisition,
    close,
    funnel,
    save_requisition,
    visible_requisitions,
)

section = require_section("recruitment", "openings")


def _superadmin(request):
    # Only the superadmin releases requisitions; others with access just read.
    if not request.user.is_superuser:
        raise PermissionDenied


def _requisition(request, pk):
    return get_object_or_404(visible_requisitions(request.companies), pk=pk)


@section
def requisition_list(request):
    status = request.GET.get("status", "")
    return render(
        request,
        "hiring/list.html",
        {
            "requisitions": visible_requisitions(request.companies, status),
            "status": status,
            "statuses": Requisition.Status.choices,
        },
    )


@section
@require_GET
def export_requisitions(request):
    status = request.GET.get("status", "")
    return requisitions_workbook(visible_requisitions(request.companies, status))


@section
def new_requisition(request):
    _superadmin(request)
    form = RequisitionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # shortcut: all-companies view files it under the first company,
        # add a company picker if that matters
        form.instance.company = request.companies[0]
        form.instance.opened_by = request.user
        save_requisition(form)
        messages.success(request, "Requisition released.")
        return redirect("hiring:list")
    return render(request, "hiring/form.html", {"form": form, "requisition": None})


@section
def edit_requisition(request, pk):
    _superadmin(request)
    requisition = _requisition(request, pk)
    form = RequisitionForm(
        request.POST or None,
        instance=requisition,
        initial={"version": requisition.version},
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_requisition(form, form.cleaned_data["version"])
        except StaleRequisition:
            messages.error(
                request,
                "Someone else changed this requisition while you were editing. "
                "Your changes were not saved.",
            )
            return redirect("hiring:edit", pk=pk)
        messages.success(request, "Saved.")
        return redirect("hiring:list")
    return render(
        request, "hiring/form.html", {"form": form, "requisition": requisition}
    )


@section
@require_POST
def close_requisition(request, pk):
    _superadmin(request)
    close(_requisition(request, pk))
    messages.success(request, "Requisition closed.")
    return redirect("hiring:list")


@section
def report(request):
    rows = [(r, [getattr(r, f) for _, f in STEPS]) for r in funnel(request.companies)]
    return render(
        request,
        "hiring/report.html",
        {"rows": rows, "heads": [h for h, _ in STEPS]},
    )


@section
@require_GET
def export_report(request):
    return funnel_workbook(funnel(request.companies))
