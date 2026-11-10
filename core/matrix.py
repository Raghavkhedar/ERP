"""Changing who can open which tab, and writing it down.

Every change to a grant or a matrix manager goes through here: the permission
check, the change and its history row happen together or not at all.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.access import MODULES
from core.models import AccessGrant, AccessLog, AccessManager

Action = AccessLog.Action


class MatrixError(ValueError):
    """The request names something that does not exist or cannot be changed."""


def can_manage(user, company):
    """Superadmins manage every company; managers only their own."""
    if not (user.is_authenticated and user.is_active):
        return False
    if user.is_superuser:
        return True
    return AccessManager.objects.filter(
        user=user, company=company, company__memberships__user=user
    ).exists()


def eligible(subject, company):
    return (
        subject.is_active
        and not subject.is_superuser
        and company.memberships.filter(user=subject).exists()
    )


def _log(actor, subject, company, action, module="", section="", note=""):
    AccessLog.objects.create(
        actor=actor,
        actor_name=actor.display_name if actor else "",
        subject=subject,
        subject_name=subject.display_name,
        company=company,
        module=module,
        section=section,
        action=action,
        note=note,
    )


def _check_target(subject, company, module, tab=None):
    if module not in MODULES or (
        tab is not None and tab not in MODULES[module].sections
    ):
        raise MatrixError("Unknown module or tab")
    if not eligible(subject, company):
        raise MatrixError("That person is not an active member of this company")


def _superadmin_only(actor):
    if not (actor.is_active and actor.is_superuser):
        raise PermissionDenied


@transaction.atomic
def set_tab(actor, subject, company, module, tab, on):
    """Turn one tab on or off. True when that changed anything."""
    if not can_manage(actor, company):
        raise PermissionDenied
    if subject.pk == actor.pk and not actor.is_superuser:
        raise PermissionDenied  # nobody widens their own access
    _check_target(subject, company, module, tab)
    if on:
        _, changed = AccessGrant.objects.get_or_create(
            user=subject,
            company=company,
            module=module,
            section=tab,
            defaults={"granted_by": actor},
        )
    else:
        changed = bool(
            AccessGrant.objects.filter(
                user=subject, company=company, module=module, section=tab
            ).delete()[0]
        )
    if changed:
        _log(
            actor, subject, company, Action.GRANT if on else Action.REVOKE, module, tab
        )
    return changed


@transaction.atomic
def set_module(actor, subject, company, module, on):
    """The All button: every tab of the module on or off. Returns tabs changed."""
    _superadmin_only(actor)
    _check_target(subject, company, module)
    changed = 0
    for tab in MODULES[module].sections:
        if on:
            _, made = AccessGrant.objects.get_or_create(
                user=subject,
                company=company,
                module=module,
                section=tab,
                defaults={"granted_by": actor},
            )
            changed += made
        else:
            changed += AccessGrant.objects.filter(
                user=subject, company=company, module=module, section=tab
            ).delete()[0]
    if changed:
        _log(
            actor,
            subject,
            company,
            Action.GRANT_MODULE if on else Action.REVOKE_MODULE,
            module,
        )
    return changed


@transaction.atomic
def add_manager(actor, subject, company):
    _superadmin_only(actor)
    if not eligible(subject, company):
        raise MatrixError("That person is not an active member of this company")
    _, made = AccessManager.objects.get_or_create(
        user=subject, company=company, defaults={"granted_by": actor}
    )
    if made:
        _log(actor, subject, company, Action.MANAGER_ADD)
    return made


@transaction.atomic
def remove_manager(actor, subject, company):
    _superadmin_only(actor)
    removed = bool(
        AccessManager.objects.filter(user=subject, company=company).delete()[0]
    )
    if removed:
        _log(actor, subject, company, Action.MANAGER_REMOVE)
    return removed


@transaction.atomic
def drop_company_grants(actor, subject, company):
    """Someone leaves a company: their grants and manager role there go too."""
    grants = list(AccessGrant.objects.filter(user=subject, company=company))
    for grant in grants:
        _log(
            actor,
            subject,
            company,
            Action.MEMBERSHIP_REMOVED,
            grant.module,
            grant.section,
        )
    AccessGrant.objects.filter(pk__in=[g.pk for g in grants]).delete()
    if AccessManager.objects.filter(user=subject, company=company).delete()[0]:
        _log(actor, subject, company, Action.MANAGER_REMOVE, note="left the company")
    return len(grants)


def rows(company):
    """The matrix rows: active non-superuser members and what each holds here."""
    users = (
        get_user_model()
        .objects.filter(
            is_active=True, is_superuser=False, memberships__company=company
        )
        .order_by("first_name", "username")
    )
    held = {}
    for user_id, module, section in AccessGrant.objects.filter(
        company=company, user__in=users
    ).values_list("user_id", "module", "section"):
        held.setdefault(user_id, set()).add((module, section))
    return [{"user": u, "held": held.get(u.pk, set())} for u in users]
