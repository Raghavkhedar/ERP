"""Which modules exist, and who may open which part of them.

A module is split into sections. Superusers can open everything; anyone else
needs an AccessGrant for the section, for a company they belong to. Grants are
handed out on the access matrix (core.matrix), by the superadmin or a manager.
"""

from dataclasses import dataclass
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from core.models import AccessGrant, Company

ALL = "all"
SESSION_KEY = "company"


@dataclass(frozen=True)
class Module:
    label: str
    sections: dict
    in_matrix: bool = True  # False for placeholders that have no pages yet


MODULES = {
    "hr": Module(
        "HR",
        {"employees": "Employees", "leave": "Leave", "payroll": "Payroll"},
        in_matrix=False,
    ),
    "finance": Module(
        "Finance",
        {"ledger": "Ledger", "invoices": "Invoices", "reports": "Reports"},
        in_matrix=False,
    ),
    "sales": Module(
        "Sales",
        {"leads": "Leads", "deals": "Deals", "customers": "Customers"},
        in_matrix=False,
    ),
    "recruitment": Module(
        "Empanelment",
        {
            "openings": "Preparing",
            "people": "People",
            "sourcing": "Sourcing",
            "screening": "Screening",
            "calling": "Calling",
            "selecting": "Selecting",
            "assessments": "HR assessments",
            "hiring": "Hiring",
            "onboarding": "On-Boarding",
        },
    ),
}


# Where each Empanelment tab lands. Assessments has no page of its own: it is
# a form reached from Hiring.
TAB_URLS = {
    "openings": "hiring:list",
    "people": "people:list",
    "sourcing": "hiring:sourcing",
    "screening": "hiring:screening",
    "calling": "hiring:calling",
    "selecting": "hiring:selecting",
    "hiring": "hiring:offers",
    "onboarding": "hiring:onboarding",
}


def user_companies(user):
    """The companies a person can work in."""
    if user.is_superuser:
        return Company.objects.all()
    return Company.objects.filter(memberships__user=user)


def _grants(user, module, section=None):
    grants = AccessGrant.objects.filter(
        user=user, module=module, company__memberships__user=user
    )
    return grants.filter(section=section) if section else grants


def companies_with_access(user, module, section):
    """The companies in which this person may open the section."""
    if not user.is_active:
        return Company.objects.none()
    if user.is_superuser:
        return Company.objects.all()
    ids = _grants(user, module, section).values("company_id")
    return Company.objects.filter(pk__in=ids)


def has_module(user, module):
    """Whether anything in the module is open to this person."""
    if not (user.is_authenticated and user.is_active):
        return False
    return user.is_superuser or _grants(user, module).exists()


def selected_company(request):
    """The company chosen in the switcher, or None for all of them."""
    choices = user_companies(request.user)
    slug = request.session.get(SESSION_KEY)
    if slug and slug != ALL:
        company = choices.filter(slug=slug).first()
        if company:
            return company
    if slug == ALL:
        return None
    # Never chosen: someone in one company works in it, others see everything.
    only = list(choices[:2])
    return only[0] if len(only) == 1 else None


def scope(request, module, section):
    """The companies a view should read: the selection, narrowed to access."""
    allowed = companies_with_access(request.user, module, section)
    company = selected_company(request)
    return allowed.filter(pk=company.pk) if company else allowed


def require_section(module, *sections):
    """Open a view only to people granted a section (any of them). Others get 403.

    Sets request.companies to the companies to read for the current switcher
    selection. In all-companies view that's every company they hold access to.
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            found = {
                c.pk: c for section in sections for c in scope(request, module, section)
            }
            request.companies = list(found.values())
            if not request.companies:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def held_tabs(user):
    """The Empanelment tabs this person may open in any of their companies."""
    if not (user.is_authenticated and user.is_active):
        return set()
    if user.is_superuser:
        return set(MODULES["recruitment"].sections)
    return set(_grants(user, "recruitment").values_list("section", flat=True))


def first_tab_url(user):
    """The first Empanelment page this person may open, or None."""
    held = held_tabs(user)
    name = next((n for tab, n in TAB_URLS.items() if tab in held), None)
    return reverse(name) if name else None
