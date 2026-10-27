"""Which modules exist, and who may open which part of them.

A module is split into sections. Superusers can open everything; anyone else
needs an AccessGrant for the section, for a company they belong to. Office
admins hand out grants, except for modules marked superadmin_only.
"""

from dataclasses import dataclass
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from core.models import AccessGrant, Company

ALL = "all"
SESSION_KEY = "company"


@dataclass(frozen=True)
class Module:
    label: str
    sections: dict
    superadmin_only: bool = False


MODULES = {
    "hr": Module(
        "HR",
        {"employees": "Employees", "leave": "Leave", "payroll": "Payroll"},
    ),
    "finance": Module(
        "Finance",
        {"ledger": "Ledger", "invoices": "Invoices", "reports": "Reports"},
        superadmin_only=True,
    ),
    "sales": Module(
        "Sales",
        {"leads": "Leads", "deals": "Deals", "customers": "Customers"},
    ),
    "recruitment": Module(
        "Recruitment",
        {
            "openings": "Openings",
            "candidates": "Candidates",
            "interviews": "Interviews",
        },
    ),
}


def user_companies(user):
    """The companies a person can work in."""
    if user.is_superuser:
        return Company.objects.all()
    return Company.objects.filter(memberships__user=user)


def can_grant(actor, module):
    if actor.is_superuser:
        return True
    return actor.is_office_admin and not MODULES[module].superadmin_only


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


def require_section(module, section):
    """Open a view only to people granted this section. Others get 403.

    Sets request.companies to the companies to read for the current switcher
    selection. In all-companies view that's every company they hold access to.
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            request.companies = list(scope(request, module, section))
            if not request.companies:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
