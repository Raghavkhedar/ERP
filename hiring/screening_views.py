from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, Exists, F, OuterRef, Q, Subquery, Value, When
from django.http import JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from core.access import require_section
from core.pagination import paginate
from people.services import visible_people
from tasks.services import can_assign

from .departments import SUB_DEPARTMENTS
from .export import followups_workbook
from .forms import (
    BulkForm,
    CallForm,
    IncomingCallForm,
    ReassignForm,
    RescheduleForm,
    ScheduleCallForm,
    ShiftForm,
)
from .models import CallLog, FollowUp, Interview, Offer, Requisition
from .services import (
    FollowUpError,
    bulk_move,
    bulk_reassign,
    cancel,
    log_call,
    reassign,
    reschedule,
    schedule_call,
    shift_calls,
    snooze_call,
    visible_followups,
)

section = require_section("recruitment", "screening")
calling_section = require_section("recruitment", "calling")
# Working one follow-up (the Call button on Calling, the actions on Screening).
followup_section = require_section("recruitment", "screening", "calling")


def _followup(request, pk):
    return get_object_or_404(visible_followups(request.user, request.companies), pk=pk)


def _can_reassign(user):
    return user.is_superuser or can_assign(user)


def _day(f):
    return timezone.localtime(f.due).date()


def _groups(request):
    rows = visible_followups(request.user, request.companies)
    today = timezone.localdate()
    day = _day
    return {
        "overdue": [f for f in rows if day(f) < today],
        "today": [f for f in rows if day(f) == today],
        "later": [f for f in rows if day(f) > today],
    }


STAGES = [
    ("screening", "Screening"),
    ("interviewed", "Interviewed"),
    ("offered", "Offered"),
    ("accepted", "Accepted"),
    ("declined", "Declined"),
]
TAGS = [*CallLog.Outcome.choices, ("none", "Not called yet")]


def _sheet(rows, get):
    """Every pending follow-up as a spreadsheet row, narrowed by the column filters."""
    person = OuterRef("person")
    rows = rows.annotate(
        last_tag=Subquery(
            CallLog.objects.filter(person=person, not_a_call=False).values("outcome")[
                :1
            ]
        ),
        offer_state=Subquery(
            Offer.objects.filter(person=person)
            .order_by("-created_at", "-id")
            .values("state")[:1]
        ),
        interviewed=Exists(Interview.objects.filter(person=person)),
    ).annotate(
        stage=Case(
            When(offer_state__isnull=False, then=F("offer_state")),
            When(interviewed=True, then=Value("interviewed")),
            default=Value("screening"),
        )
    )
    if q := get.get("q", "").strip():
        rows = rows.filter(person__name__icontains=q)
    if day := parse_date(get.get("due_from", "")):
        rows = rows.filter(due__date__gte=day)
    if day := parse_date(get.get("due_to", "")):
        rows = rows.filter(due__date__lte=day)
    if purposes := get.getlist("purpose"):
        rows = rows.filter(purpose__in=purposes)
    if stages := get.getlist("stage"):
        rows = rows.filter(stage__in=stages)
    if tags := get.getlist("tag"):
        match = Q(last_tag__in=tags)
        if "none" in tags:
            match |= Q(last_tag__isnull=True)
        rows = rows.filter(match)
    if departments := get.getlist("department"):
        rows = rows.filter(requisition__department__in=departments)
    if subs := get.getlist("sub"):
        rows = rows.filter(requisition__sub_department__in=subs)
    if get.get("owner", "").isdigit():
        rows = rows.filter(owner_id=get["owner"])
    return rows


def _dept_data(base, get):
    """What the department filters offer: each department with its sub-departments
    (the fixed list plus any other value typed on a requisition), and what is ticked."""
    typed = {}
    for dept, name in base.values_list(
        "requisition__department", "requisition__sub_department"
    ).distinct():
        if name:
            typed.setdefault(dept, set()).add(name)
    groups = []
    for value, label in Requisition.Department.choices:
        subs = list(SUB_DEPARTMENTS.get(value, []))
        subs += sorted(typed.get(value, set()) - set(subs))
        groups.append({"value": value, "label": label, "subs": subs})
    return {
        "departments": Requisition.Department.choices,
        "groups": groups,
        "deps": get.getlist("department"),
        "subs": get.getlist("sub"),
    }


def _summary(rows, today):
    """The numbers above the sheet: what is due today, and who holds it."""
    today_q = Q(due__date=today)
    per_owner = (
        rows.filter(due__date__lte=today)
        .order_by()
        .values("owner")
        .annotate(
            today=Count("id", filter=today_q),
            overdue=Count("id", filter=Q(due__date__lt=today)),
            interview=Count("id", filter=today_q & Q(purpose="interview")),
            offer=Count("id", filter=today_q & Q(purpose="offer")),
        )
    )
    owners = get_user_model().objects.in_bulk([r["owner"] for r in per_owner])
    by_owner = sorted(
        ({**r, "owner": owners[r["owner"]]} for r in per_owner),
        key=lambda r: -(r["today"] + r["overdue"]),
    )
    return {
        "today": sum(r["today"] for r in by_owner),
        "overdue": sum(r["overdue"] for r in by_owner),
        "interview": sum(r["interview"] for r in by_owner),
        "offer": sum(r["offer"] for r in by_owner),
        "people": len(by_owner),
        "by_owner": by_owner,
    }


@section
def screening(request):
    base = visible_followups(request.user, request.companies)
    tags, stages = dict(TAGS), dict(STAGES)
    page = paginate(request, _sheet(base, request.GET))
    rows = list(page)
    for f in rows:
        f.tag_label = tags.get(f.last_tag or "none")
        f.stage_label = stages[f.stage]
        f.overdue = _day(f) < timezone.localdate()
    return render(
        request,
        "hiring/screening.html",
        {
            "summary": _summary(base, timezone.localdate()),
            "rows": rows,
            "page": page,
            "owners": get_user_model().objects.filter(pk__in=base.values("owner")),
            "purposes": FollowUp.Purpose.choices,
            "tags": TAGS,
            "stages": STAGES,
            "get": request.GET,
            "picked": {k: request.GET.getlist(k) for k in ("purpose", "tag", "stage")},
            "dept_data": _dept_data(base, request.GET),
            "can_bulk": _can_reassign(request.user),
            "page_ids": [str(f.pk) for f in rows],
            "filters": request.GET.urlencode(),
            "assignees": ReassignForm(companies=request.companies)
            .fields["owner"]
            .queryset,
            "reasons": FollowUp.Reason.choices,
            "today": timezone.localdate().isoformat(),
            "filtered": any(request.GET.values()),
            "shift_form": ShiftForm(),
        },
    )


def _mine(request):
    return visible_followups(request.user, request.companies).filter(owner=request.user)


@calling_section
def calling(request):
    stages, tags = dict(STAGES), dict(TAGS)
    page = paginate(request, _sheet(_mine(request), QueryDict()))
    rows = list(page)
    for f in rows:
        f.tag_label = tags.get(f.last_tag or "none")
        f.stage_label = stages[f.stage]
        f.overdue = _day(f) < timezone.localdate()
    return render(request, "hiring/calling.html", {"rows": rows, "page": page})


@calling_section
@require_GET
def export_calling(request):
    return followups_workbook(_mine(request))


@section
@require_POST
def bulk(request):
    """Assign, or move the date of, the ticked follow-ups or all a filter matches."""
    if not _can_reassign(request.user):
        raise PermissionDenied
    filters = QueryDict(request.POST.get("filters", ""))
    back = reverse("hiring:screening") + (f"?{filters.urlencode()}" if filters else "")
    form = BulkForm(request.POST, companies=request.companies)
    if not form.is_valid():
        messages.error(request, next(iter(form.errors.values()))[0])
        return redirect(back)
    d = form.cleaned_data
    seen = visible_followups(request.user, request.companies)
    if d["scope"] == "all":
        seen = _sheet(seen, filters)
    else:
        ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
        seen = seen.filter(pk__in=ids)
    pks = list(seen.order_by().values_list("pk", flat=True))
    if not pks:
        messages.error(request, "Nothing is selected.")
        return redirect(back)
    rows = FollowUp.objects.filter(pk__in=pks, status=FollowUp.Status.PENDING)
    if d["do"] == "assign":
        n = bulk_reassign(rows, d["owner"], request.user)
        messages.success(
            request,
            f"Gave {n} follow-up{'s' if n != 1 else ''} to {d['owner'].display_name}.",
        )
    else:
        n = bulk_move(rows, d["day"], d["reason"])
        day = f"{d['day'].day} {d['day']:%b}"
        messages.success(
            request, f"Moved {n} follow-up{'s' if n != 1 else ''} to {day}."
        )
    return redirect(back)


@section
@require_POST
def shift(request):
    form = ShiftForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Pick a day and a reason to move them.")
        return redirect("hiring:screening")
    d = form.cleaned_data
    try:
        moved = shift_calls(_groups(request)[d["group"]], d["day"], d["reason"])
    except FollowUpError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Moved {moved} call{'s' if moved != 1 else ''}.")
    return redirect("hiring:screening")


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
            "call_action": reverse("hiring:followup_call", args=[followup.pk]),
            "call_form": forms.get("call_form") or CallForm(),
            "reschedule_form": forms.get("reschedule_form") or RescheduleForm(),
            "reassign_form": (
                forms.get("reassign_form") or ReassignForm(companies=request.companies)
                if _can_reassign(request.user)
                else None
            ),
        },
    )


@followup_section
def followup_detail(request, pk):
    return _detail(request, _followup(request, pk))


def _act(
    request, pk, form_class, form_key, run, done, back="hiring:calling", **form_kwargs
):
    followup = _followup(request, pk)
    form = form_class(request.POST, **form_kwargs)
    if form.is_valid():
        try:
            run(followup, form.cleaned_data)
        except FollowUpError as exc:
            messages.error(request, str(exc))
            return redirect(back)
        messages.success(request, done)
        return redirect(back)
    return _detail(request, followup, **{form_key: form})


def _call_args(d):
    return dict(
        outcome=d["outcome"],
        notes=d["notes"],
        next_due=d["next_due"],
        intention=d["intention"],
        intention_other=d["intention_other"].strip(),
        call_type=d["call_type"],
        rescheduled=d["rescheduled"],
        reschedule_reason=d["reschedule_reason"].strip(),
        department_changed=d["department_changed"],
        discuss=d["discuss"],
    )


@followup_section
@require_POST
def log_followup(request, pk):
    def run(f, d):
        log_call(f, user=request.user, **_call_args(d))

    return _act(request, pk, CallForm, "call_form", run, "Call logged.")


@calling_section
def call_new(request):
    """Log a call that came in, for a candidate picked by name or number."""
    form = IncomingCallForm(request.POST or None, companies=request.companies)
    if request.method == "POST" and form.is_valid():
        try:
            log_call(
                None,
                user=request.user,
                person=form.cleaned_data["person"],
                **_call_args(form.cleaned_data),
            )
        except FollowUpError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Call logged.")
            return redirect("hiring:calling")
    person = form.cleaned_data.get("person") if form.is_bound else None
    return render(
        request,
        "hiring/call_new.html",
        {
            "call_form": form,
            "call_action": reverse("hiring:call_new"),
            "picked": person
            and {"id": person.pk, "name": person.name, "phone": person.phone},
        },
    )


@calling_section
@require_GET
def calling_people(request):
    q = request.GET.get("q", "").strip()
    found = visible_people(request.companies, q)
    if q.isdigit():
        found = found | visible_people(request.companies).filter(pk=int(q))
    return JsonResponse(
        {
            "people": [
                {"id": p.pk, "name": p.name, "phone": p.phone}
                for p in found.order_by("name")[:15]
            ]
        }
    )


@followup_section
@require_POST
def reschedule_followup(request, pk):
    def run(f, d):
        reschedule(f, d["due"], d["reason"])

    return _act(request, pk, RescheduleForm, "reschedule_form", run, "Follow-up moved.")


@followup_section
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
        back="hiring:screening",
        companies=request.companies,
    )


@followup_section
@require_POST
def cancel_followup(request, pk):
    try:
        cancel(_followup(request, pk))
    except FollowUpError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Follow-up cancelled.")
    return redirect("hiring:screening")


@followup_section
@require_POST
def schedule_for_person(request, pk):
    person = get_object_or_404(visible_people(request.companies), pk=pk)
    form = ScheduleCallForm(request.POST)
    if form.is_valid():
        try:
            schedule_call(person, form.cleaned_data["due"], request.user)
        except FollowUpError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Call booked.")
    else:
        messages.error(request, "Pick a date and time for the call.")
    return redirect("people:detail", pk=person.pk)


@followup_section
@require_POST
def snooze_followup(request, pk):
    """The alarm popup's snooze and dismiss. Dismiss is an hour's quiet."""
    action = request.POST.get("action", "snooze")
    length = "1h" if action == "dismiss" else request.POST.get("length", "")
    try:
        snooze_call(_followup(request, pk), request.user, length)
    except FollowUpError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True})
