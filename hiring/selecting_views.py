from pathlib import Path

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.access import companies_with_access, require_section
from core.pagination import paginate

from .export import interviews_workbook
from .interview_form import (
    COLUMN_TYPES,
    SECTIONS,
    TABLES,
    AssessmentForm,
    InterviewForm,
    read_tables,
    table_shows,
)
from .models import Interview
from .services import (
    FollowUpError,
    edit_interview,
    interviews_waiting,
    record_interview,
    save_assessment,
    visible_interviews,
)

section = require_section("recruitment", "selecting")
hiring_section = require_section("recruitment", "hiring")


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
            "waiting": paginate(
                request,
                interviews_waiting(request.user, request.companies),
                param="wpage",
            ),
            "done": visible_interviews(request.companies)[:100],
        },
    )


@section
@require_GET
def export_interviews(request):
    return interviews_workbook(
        visible_interviews(request.companies), include_hr=_has_hr(request)
    )


def _initial(person):
    """What the card already knows, to start the form from."""
    return {
        "date": timezone.localdate().isoformat(),
        "email": person.email,
        "temporary_address": person.address,
        "permanent_address": person.permanent_address,
        "highest_education": person.highest_education,
        "experience_months": person.experience_years
        and round(person.experience_years * 12),
        "expected_salary": person.expected_salary and int(person.expected_salary),
        "joining_days": "".join(c for c in person.joining_period if c.isdigit()),
        "place_of_birth": person.place_of_birth,
        "date_of_birth": person.date_of_birth and person.date_of_birth.isoformat(),
        "time_of_birth": person.time_of_birth
        and person.time_of_birth.strftime("%H:%M"),
        "alternate_phone": person.alternate_phone,
    }


def _files(request, interview):
    """Keep an uploaded photo or resume; a file not sent leaves the old one."""
    for name in ("photo", "resume"):
        if request.FILES.get(name):
            setattr(interview, name, request.FILES[name])
    interview.save(update_fields=["photo", "resume"])


@hiring_section
def interview_file(request, pk, name):
    interview = get_object_or_404(visible_interviews(request.companies), pk=pk)
    file = getattr(interview, name, None) if name in ("photo", "resume") else None
    if not file:
        raise Http404
    return FileResponse(file.open("rb"), filename=Path(file.name).name)


def _tables(request, interview=None, saved=False):
    """Every table's rows: as posted, else as saved. Posted rows of a table the
    chosen profile doesn't show are dropped."""
    if request.method == "POST" and not saved:
        profile = request.POST.get("profile", "")
        got = read_tables(request.POST, profile)
        return {**{k: [] for k in TABLES}, **got}
    saved = interview.answers if interview else {}
    return {k: saved.get(k, []) for k in TABLES}


def _sections(form):
    """The common questions as the page's groups of fields."""
    return [
        {"title": title, "fields": [form[k] for k in keys]} for title, keys in SECTIONS
    ]


def _page(request, form, person, when, tables, **extra):
    shows = table_shows()
    return render(
        request,
        "hiring/interview_form.html",
        {
            "person": person,
            "when": when,
            "form": form,
            "tables": tables,
            "sections": _sections(form),
            "today": timezone.localdate().isoformat(),
            "table_defs": [
                {
                    "key": k,
                    "prefix": p,
                    "title": t,
                    "show": shows[k],
                    "cols": [
                        {
                            "key": c,
                            "label": label,
                            "type": COLUMN_TYPES.get(c, "text")
                            if k == "work"
                            else "text",
                        }
                        for c, label in cols.items()
                    ],
                }
                for k, (p, t, cols) in TABLES.items()
            ],
            **extra,
        },
    )


@section
def record(request, pk):
    followup = get_object_or_404(
        interviews_waiting(request.user, request.companies), pk=pk
    )
    person = followup.person
    form = InterviewForm(
        request.POST or None, initial=_initial(person), user=request.user
    )
    tables = _tables(request)
    if request.method == "POST" and form.is_valid():
        try:
            interview = record_interview(
                followup,
                Interview.Result.PENDING,
                request.user,
                profile=form.cleaned_data["profile"],
                answers={**form.answers(), **tables},
            )
        except FollowUpError as exc:
            messages.error(request, str(exc))
        else:
            _files(request, interview)
            messages.success(request, "Interview form filed.")
        return redirect("hiring:selecting")
    return _page(request, form, person, followup.due, tables)


@hiring_section
def review(request, pk):
    """Open a filed interview: edit it, and (for those allowed) fill the HR form."""
    interview = get_object_or_404(visible_interviews(request.companies), pk=pk)
    has_hr = _has_hr(request)
    existing = getattr(interview, "hr", None)
    posted = request.method == "POST"
    hr = bool(posted and has_hr and request.POST.get("which") == "hr")
    form = InterviewForm(
        request.POST if posted and not hr else None,
        initial={
            **interview.answers,
            "profile": interview.profile,
            "assessor": interview.answers.get("assessor_id"),
        },
        user=request.user,
    )
    hr_form = (
        AssessmentForm(
            request.POST if hr else None,
            initial={
                "decision": existing and existing.decision,
                "level": existing and existing.level,
                "comments": existing and existing.comments,
                **(existing.answers if existing else {}),
            },
        )
        if has_hr
        else None
    )
    tables = _tables(request, interview, saved=hr)
    if hr and hr_form.is_valid():
        d = hr_form.cleaned_data
        save_assessment(
            interview,
            d["decision"],
            d["level"],
            request.user,
            comments=d["comments"],
            answers=hr_form.answers(),
        )
        messages.success(request, "HR assessment saved.")
        return redirect("hiring:interview_review", pk=pk)
    if posted and not hr and form.is_valid():
        edit_interview(
            interview,
            interview.result,
            interview.questions,
            interview.notes,
            profile=form.cleaned_data["profile"],
            answers={**form.answers(), **tables},
        )
        _files(request, interview)
        messages.success(request, "Interview updated.")
        return redirect("hiring:interview_review", pk=pk)
    return _page(
        request,
        form,
        interview.person,
        interview.scheduled_at,
        tables,
        interview=interview,
        hr_form=hr_form,
        editing=True,
    )
