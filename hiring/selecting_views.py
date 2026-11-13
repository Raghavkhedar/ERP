import re
from pathlib import Path

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.access import companies_with_access, require_section
from core.pagination import paginate

from . import interview_form
from .departments import SUB_DEPARTMENTS
from .export import interviews_workbook
from .interview_form import (
    COLUMN_TYPES,
    PROFILE_OF,
    SECTIONS,
    TABLES,
    AssessmentForm,
    InterviewForm,
    profile_for,
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
# A filed form opens from Selecting (the interviewers) or Hiring; the HR panel on
# it is still only for those with the assessments grant (see _has_hr).
filed_section = require_section("recruitment", "selecting", "hiring")


def _hr_companies(request):
    """The active companies where this person holds the HR assessments grant."""
    return set(
        companies_with_access(request.user, "recruitment", "assessments")
        .filter(pk__in=[c.pk for c in request.companies])
        .values_list("pk", flat=True)
    )


def _has_hr(request, interview=None):
    """Whether HR assessments are open to them: for one interview, in its company."""
    held = _hr_companies(request)
    return interview.person.company_id in held if interview else bool(held)


def _can_edit(request, interview):
    """Only the interviewer, or someone holding Selecting there, may change an
    interview; Hiring opens it to read."""
    return (
        interview.interviewer_id == request.user.pk
        or companies_with_access(request.user, "recruitment", "selecting")
        .filter(pk=interview.person.company_id)
        .exists()
    )


def _filed(request):
    """Filed interviews this person may open: every one in the companies where
    they hold Hiring or Assessments, and otherwise only the ones they conducted."""
    mine = [c.pk for c in request.companies]
    wide = [
        pk
        for name in ("hiring", "assessments")
        for pk in companies_with_access(request.user, "recruitment", name)
        .filter(pk__in=mine)
        .values_list("pk", flat=True)
    ]
    return visible_interviews(request.companies).filter(
        Q(interviewer=request.user) | Q(person__company__in=wide)
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
            "done": _filed(request)[:100],
        },
    )


@section
@require_GET
def export_interviews(request):
    held = _hr_companies(request)
    return interviews_workbook(
        _filed(request), include_hr=bool(held), hr_companies=held
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
        "joining_days": joining_days(person.joining_period),
        "place_of_birth": person.place_of_birth,
        "date_of_birth": person.date_of_birth and person.date_of_birth.isoformat(),
        "time_of_birth": person.time_of_birth
        and person.time_of_birth.strftime("%H:%M"),
        "alternate_phone": person.alternate_phone,
    }


MAX_UPLOAD = 10 * 1024 * 1024


def joining_days(period):
    """Days from the card's free-text joining period: "15 days", "2 weeks", "1 month",
    or a range like "15-20 days" (its first number)."""
    found = re.search(r"(\d+)\s*(week|month)?", period or "", re.I)
    if not found:
        return ""
    unit = {"week": 7, "month": 30}.get((found[2] or "").lower(), 1)
    return int(found[1]) * unit


def _files(request, interview):
    """Keep an uploaded photo or resume; a file not sent leaves the old one."""
    for name in ("photo", "resume"):
        file = request.FILES.get(name)
        if not file:
            continue
        if file.size > MAX_UPLOAD or (
            name == "photo" and not file.content_type.startswith("image/")
        ):
            kind = "an image" if name == "photo" else "a file"
            messages.error(request, f"The {name} wasn't kept: send {kind} under 10 MB.")
            continue
        if getattr(interview, name):
            getattr(interview, name).delete(
                save=False
            )  # don't leave the old one behind
        setattr(interview, name, file)
    interview.save(update_fields=["photo", "resume"])


@filed_section
def interview_file(request, pk, name):
    interview = get_object_or_404(_filed(request), pk=pk)
    file = getattr(interview, name, None) if name in ("photo", "resume") else None
    if not file:
        raise Http404
    return FileResponse(
        file.open("rb"), filename=Path(file.name).name, as_attachment=True
    )


def _tables(request, interview=None, saved=False):
    """Every table's rows: as posted, else as saved. Posted rows of a table the
    chosen department and sub-department don't show are dropped."""
    if request.method == "POST" and not saved:
        post = request.POST
        got = read_tables(
            post, profile_for(post.get("department"), post.get("sub_department"))
        )
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
            "max_rows": interview_form.MAX_ROWS,
            "sections": _sections(form),
            "today": timezone.localdate().isoformat(),
            "sub_departments": SUB_DEPARTMENTS,
            "profile_of": {f"{d}|{s}": p for (d, s), p in PROFILE_OF.items()},
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
    req = followup.requisition
    form = InterviewForm(
        request.POST or None,
        initial={
            **_initial(person),
            # From the requisition; the interviewer can change both.
            "department": req and req.department,
            "sub_department": req and req.sub_department,
        },
        user=request.user,
    )
    tables = _tables(request)
    if request.method == "POST" and form.is_valid():
        try:
            interview = record_interview(
                followup,
                Interview.Result.PENDING,
                request.user,
                profile=form.profile,
                answers={**form.answers(), **tables},
            )
        except FollowUpError as exc:
            messages.error(request, str(exc))
        else:
            _files(request, interview)
            messages.success(request, "Interview form filed.")
        return redirect("hiring:selecting")
    return _page(request, form, person, followup.due, tables)


@filed_section
def review(request, pk):
    """Open a filed interview: edit it, and (for those allowed) fill the HR form."""
    interview = get_object_or_404(_filed(request), pk=pk)
    has_hr = _has_hr(request, interview)
    existing = getattr(interview, "hr", None)
    posted = request.method == "POST"
    hr = bool(posted and request.POST.get("which") == "hr")
    if hr and not has_hr:
        raise PermissionDenied
    if posted and not hr and not _can_edit(request, interview):
        raise PermissionDenied
    form = InterviewForm(
        request.POST if posted and not hr else None,
        initial={
            "department": interview.requisition and interview.requisition.department,
            "sub_department": interview.requisition
            and interview.requisition.sub_department,
            **interview.answers,
            "assessor": interview.answers.get("assessor_id")
            or interview.interviewer_id,
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
                "offer_given": existing
                and interview_form.offer_amount(existing.answers.get("offer_given"))
                or None,
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
            profile=form.profile,
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
