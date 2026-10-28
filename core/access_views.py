from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from core.access import ALL, MODULES, SESSION_KEY, can_grant, user_companies
from core.access_export import access_workbook
from core.models import AccessGrant, Company, Membership, User


def _office_admin(user):
    if not user.is_office_admin:
        raise PermissionDenied


@require_POST
@login_required
def switch_company(request):
    choice = request.POST.get("company", ALL)
    if choice == ALL or user_companies(request.user).filter(slug=choice).exists():
        request.session[SESSION_KEY] = choice
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        back, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        back = "/"
    return redirect(back)


def _people():
    return User.objects.filter(is_active=True, is_superuser=False).order_by(
        "first_name", "username"
    )


@login_required
def people(request):
    _office_admin(request.user)
    users = _people().prefetch_related("memberships__company")
    return render(request, "core/access_people.html", {"people": users})


@login_required
@require_GET
def export_access(request):
    """The Access page as a spreadsheet: the same people, their companies and grants."""
    _office_admin(request.user)
    return access_workbook(_people())


@login_required
def person(request, pk):
    actor = request.user
    _office_admin(actor)
    subject = get_object_or_404(User, pk=pk, is_active=True)
    if subject.is_superuser:
        raise Http404

    if request.method == "POST":
        if subject.pk == actor.pk and not actor.is_superuser:
            raise PermissionDenied  # nobody widens their own access
        with transaction.atomic():
            if request.POST.get("action") == "companies":
                _save_memberships(request, subject)
            else:
                _save_grants(request, subject)
        messages.success(request, "Saved")
        return redirect("access_person", pk=subject.pk)

    memberships = list(subject.memberships.select_related("company"))
    held = set(subject.access_grants.values_list("module", "section", "company__slug"))
    modules = [
        {
            "key": key,
            "label": module.label,
            "editable": can_grant(actor, key),
            "sections": [
                {
                    "key": section,
                    "label": label,
                    "cells": [
                        {
                            "company": m.company,
                            "value": f"{key}:{section}:{m.company.slug}",
                            "on": (key, section, m.company.slug) in held,
                        }
                        for m in memberships
                    ],
                }
                for section, label in module.sections.items()
            ],
        }
        for key, module in MODULES.items()
    ]
    by_company = {m.company_id: m for m in memberships}
    return render(
        request,
        "core/access_person.html",
        {
            "subject": subject,
            "rows": [
                {"company": c, "membership": by_company.get(c.pk)}
                for c in Company.objects.all()
            ],
            "memberships": memberships,
            "modules": modules,
        },
    )


def _save_memberships(request, subject):
    chosen = set(request.POST.getlist("company"))
    companies = list(Company.objects.filter(slug__in=chosen))
    subject.memberships.exclude(company__in=companies).delete()
    # Grants the actor may not give, they may not take away either.
    for grant in subject.access_grants.exclude(company__in=companies):
        if can_grant(request.user, grant.module):
            grant.delete()
    for company in companies:
        Membership.objects.update_or_create(
            user=subject,
            company=company,
            defaults={
                "designation": request.POST.get(
                    f"designation_{company.slug}", ""
                ).strip()[:100],
                "pays_salary": False,
            },
        )
    # One company pays; with a single company that one has to.
    paying = request.POST.get("paid_by")
    pay_company = next((c for c in companies if c.slug == paying), None)
    if pay_company is None and companies:
        pay_company = companies[0]
    if pay_company:
        subject.memberships.filter(company=pay_company).update(pays_salary=True)


def _save_grants(request, subject):
    actor = request.user
    wanted = set()
    for value in request.POST.getlist("grant"):
        try:
            module, section, slug = value.split(":")
        except ValueError:
            continue
        if module in MODULES and section in MODULES[module].sections:
            wanted.add((module, section, slug))
    members = {
        m.company.slug: m.company for m in subject.memberships.select_related("company")
    }
    for module in MODULES:
        if not can_grant(actor, module):
            continue
        existing = {
            (g.section, g.company.slug): g
            for g in subject.access_grants.filter(module=module).select_related(
                "company"
            )
        }
        target = {(s, slug) for m, s, slug in wanted if m == module and slug in members}
        for key, grant in existing.items():
            if key not in target:
                grant.delete()
        for section, slug in target - existing.keys():
            AccessGrant.objects.create(
                user=subject,
                company=members[slug],
                module=module,
                section=section,
                granted_by=actor,
            )
