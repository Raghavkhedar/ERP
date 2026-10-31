from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from core.access import companies_with_access, require_section

from .export import interviews_workbook
from .forms import AssessmentForm, InterviewForm
from .models import Interview
from .services import (
    FollowUpError,
    interviews_waiting,
    record_interview,
    save_assessment,
    visible_interviews,
)

section = require_section("recruitment", "candidates")
hr_section = require_section("recruitment", "assessments")


def _has_hr(request):
    return (
        companies_with_access(request.user, "recruitment", "assessments")
        .filter(pk__in=[c.pk for c in request.companies])
        .exists()
    )


@section
def selecting(request):
    return render(
        request,
        "hiring/selecting.html",
        {
            "waiting": interviews_waiting(request.user, request.companies),
            "done": visible_interviews(request.companies)[:100],
            "has_hr": _has_hr(request),
        },
    )


@section
@require_GET
def export_interviews(request):
    return interviews_workbook(
        visible_interviews(request.companies), include_hr=_has_hr(request)
    )


@section
def record(request, pk):
    followup = get_object_or_404(
        interviews_waiting(request.user, request.companies), pk=pk
    )
    form = InterviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            record_interview(
                followup,
                d["result"],
                request.user,
                d["questions"],
                d["notes"],
                d["next_due"],
            )
        except FollowUpError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Interview recorded.")
        return redirect("hiring:selecting")
    return render(request, "hiring/interview_form.html", {"f": followup, "form": form})


@hr_section
def assess(request, pk):
    interview = get_object_or_404(
        Interview, pk=pk, person__company__in=request.companies
    )
    existing = getattr(interview, "hr", None)
    form = AssessmentForm(request.POST or None, instance=existing)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        save_assessment(
            interview,
            d["decision"],
            d["level"],
            request.user,
            d["hold_tenure"],
            d["comments"],
        )
        messages.success(request, "HR assessment saved.")
        return redirect("hiring:selecting")
    return render(
        request, "hiring/assess_form.html", {"interview": interview, "form": form}
    )
