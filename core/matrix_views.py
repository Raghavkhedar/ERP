"""The access matrix page: who may open which tab, per company."""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from core import matrix
from core.access import MODULES
from core.models import AccessGrant, Company


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
    rows = [
        r
        for r in matrix.rows(company)
        if q in r["user"].display_name.lower() or q in r["user"].username.lower()
    ]
    rows = [{**r, "cells": _cells(r["held"])} for r in rows]
    return render(
        request,
        "core/access_matrix.html",
        {
            "company": company,
            "companies": allowed,
            "rows": rows,
            "q": request.GET.get("q", ""),
            "modules": [m for _, m in _modules()],
            "is_super": request.user.is_superuser,
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
