"""The access matrix page: who may open which tab, per company."""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core import matrix
from core.access import MODULES
from core.matrix_export import history_workbook, matrix_workbook
from core.models import AccessGrant, AccessLog, AccessManager, Company


def _modules():
    return [(key, m) for key, m in MODULES.items() if m.in_matrix]


def _company(request):
    """The company on show: ?company=, or the first one they manage."""
    allowed = list(matrix.managed_companies(request.user))
    if not allowed:
        raise PermissionDenied
    slug = request.GET.get("company")
    if not slug:
        return allowed[0], allowed
    company = next((c for c in allowed if c.slug == slug), None)
    if company is None:
        raise PermissionDenied  # never quietly show a different company
    return company, allowed


def _cells(held):
    """One entry per module: its tabs with whether this person holds each."""
    return [
        {
            "key": key,
            "label": module.label,
            "all_on": all((key, tab) in held for tab in module.sections),
            "tabs": [
                {"key": tab, "label": label, "on": (key, tab) in held}
                for tab, label in module.sections.items()
            ],
        }
        for key, module in _modules()
    ]


def _context(company, row, is_super):
    return {
        "company": company,
        "row": {**row, "cells": _cells(row["held"])},
        "is_super": is_super,
    }


@login_required
def matrix_page(request):
    company, allowed = _company(request)
    q = request.GET.get("q", "").strip().lower()
    everyone = matrix.rows(company)
    rows = [
        {**r, "cells": _cells(r["held"])}
        for r in everyone
        if q in r["user"].display_name.lower() or q in r["user"].username.lower()
    ]
    history = Paginator(AccessLog.objects.filter(company=company), 25).get_page(
        request.GET.get("page")
    )
    is_super = request.user.is_superuser
    current = AccessManager.objects.filter(company=company).select_related("user")
    taken = {m.user_id for m in current}
    choosable = [r["user"] for r in everyone if r["user"].pk not in taken]
    return render(
        request,
        "core/access_matrix.html",
        {
            "company": company,
            "companies": allowed,
            "rows": rows,
            "q": request.GET.get("q", ""),
            "modules": [m for _, m in _modules()],
            "is_super": is_super,
            "history": history,
            "managers": current if is_super else [],
            "choosable": choosable if is_super else [],
        },
    )


def _target(request):
    company = get_object_or_404(Company, slug=request.POST.get("company", ""))
    if not matrix.can_manage(request.user, company):
        raise PermissionDenied
    subject = get_object_or_404(get_user_model(), pk=_pk(request.POST.get("user")))
    return company, subject


def _pk(value):
    return int(value) if str(value).isdigit() else 0


def _on(request):
    value = request.POST.get("on")
    return {"1": True, "0": False}.get(value)


def _reply(request, company, subject):
    row = {
        "user": subject,
        "held": set(
            AccessGrant.objects.filter(user=subject, company=company).values_list(
                "module", "section"
            )
        ),
    }
    return render(
        request,
        "core/_matrix_row.html",
        _context(company, row, request.user.is_superuser),
    )


@login_required
@require_POST
def cell(request):
    company, subject = _target(request)
    on = _on(request)
    if on is None:
        return HttpResponseBadRequest("Bad value")
    try:
        matrix.set_tab(
            request.user,
            subject,
            company,
            request.POST.get("module", ""),
            request.POST.get("tab", ""),
            on,
        )
    except matrix.MatrixError as error:
        return HttpResponseBadRequest(str(error))
    return _reply(request, company, subject)


@login_required
@require_POST
def module(request):
    company, subject = _target(request)
    on = _on(request)
    if on is None:
        return HttpResponseBadRequest("Bad value")
    try:
        matrix.set_module(
            request.user, subject, company, request.POST.get("module", ""), on
        )
    except matrix.MatrixError as error:
        return HttpResponseBadRequest(str(error))
    return _reply(request, company, subject)


@login_required
@require_POST
def managers(request):
    """Superadmin only: name or remove the people who look after a company's matrix."""
    company = get_object_or_404(Company, slug=request.POST.get("company", ""))
    if not request.user.is_superuser:
        raise PermissionDenied
    subject = get_object_or_404(get_user_model(), pk=_pk(request.POST.get("user")))
    action = request.POST.get("action")
    change = {"add": matrix.add_manager, "remove": matrix.remove_manager}.get(action)
    if change is None:
        return HttpResponseBadRequest("Bad action")
    try:
        change(request.user, subject, company)
    except matrix.MatrixError as error:
        return HttpResponseBadRequest(str(error))
    return redirect(f"{reverse('access_matrix')}?company={company.slug}")


@login_required
@require_GET
def export_matrix(request):
    company, _ = _company(request)
    return matrix_workbook(company, matrix.rows(company))


@login_required
@require_GET
def export_history(request):
    company, _ = _company(request)
    return history_workbook(company, AccessLog.objects.filter(company=company))
