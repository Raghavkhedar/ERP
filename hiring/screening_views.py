from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.access import require_section
from tasks.services import can_assign

from .export import followups_workbook
from .forms import CallForm, ReassignForm, RescheduleForm
from .models import CallLog
from .services import (
    FollowUpError,
    cancel,
    log_call,
    reassign,
    reschedule,
    visible_followups,
)

section = require_section("recruitment", "candidates")


def _followup(request, pk):
    return get_object_or_404(visible_followups(request.user, request.companies), pk=pk)


def _can_reassign(user):
    return user.is_superuser or can_assign(user)


@section
def screening(request):
    rows = visible_followups(request.user, request.companies)
    now = timezone.localtime()
    overdue = [f for f in rows if f.due < now and f.due.date() < now.date()]
    today = [f for f in rows if f.due.date() == now.date()]
    later = [f for f in rows if f.due.date() > now.date()]
    return render(
        request,
        "hiring/screening.html",
        {"groups": [("Overdue", overdue), ("Today", today), ("Later", later)]},
    )


@section
@require_GET
def export_followups(request):
    return followups_workbook(visible_followups(request.user, request.companies))


def _detail(request, followup, **forms):
    return render(
        request,
        "hiring/followup.html",
        {
            "f": followup,
            "calls": CallLog.objects.filter(person=followup.person).select_related(
                "caller"
            )[:10],
            "call_form": forms.get("call_form") or CallForm(),
            "reschedule_form": forms.get("reschedule_form") or RescheduleForm(),
            "reassign_form": (
                forms.get("reassign_form") or ReassignForm(companies=request.companies)
                if _can_reassign(request.user)
                else None
            ),
        },
    )


@section
def followup_detail(request, pk):
    return _detail(request, _followup(request, pk))


def _act(request, pk, form_class, form_key, run, done, **form_kwargs):
    followup = _followup(request, pk)
    form = form_class(request.POST, **form_kwargs)
    if form.is_valid():
        try:
            run(followup, form.cleaned_data)
        except FollowUpError as exc:
            messages.error(request, str(exc))
            return redirect("hiring:screening")
        messages.success(request, done)
        return redirect("hiring:screening")
    return _detail(request, followup, **{form_key: form})


@section
@require_POST
def log_followup(request, pk):
    def run(f, d):
        log_call(f, d["outcome"], request.user, d["notes"], d["next_due"])

    return _act(request, pk, CallForm, "call_form", run, "Call logged.")


@section
@require_POST
def reschedule_followup(request, pk):
    def run(f, d):
        reschedule(f, d["due"], d["reason"])

    return _act(request, pk, RescheduleForm, "reschedule_form", run, "Follow-up moved.")


@section
@require_POST
def reassign_followup(request, pk):
    if not _can_reassign(request.user):
        raise PermissionDenied

    def run(f, d):
        reassign(f, d["owner"], request.user)

    return _act(
        request,
        pk,
        ReassignForm,
        "reassign_form",
        run,
        "Follow-up reassigned.",
        companies=request.companies,
    )


@section
@require_POST
def cancel_followup(request, pk):
    try:
        cancel(_followup(request, pk))
    except FollowUpError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Follow-up cancelled.")
    return redirect("hiring:screening")
