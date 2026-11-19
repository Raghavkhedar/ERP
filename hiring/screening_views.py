from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, Exists, F, OuterRef, Q, Subquery, Value, When
from django.http import HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_POST

from core.access import require_section
from core.pagination import paginate
from people.models import Person, phone_key
from people.services import visible_people
from tasks.services import can_assign

from . import whereabouts
from .departments import SUB_DEPARTMENTS
from .export import call_logs_workbook, followups_workbook
from .forms import (
    BulkForm,
    CallForm,
    CallLogEditForm,
    IncomingCallForm,
    ReassignForm,
    RescheduleForm,
    ScheduleCallForm,
)
from .models import CallLog, FollowUp, Interview, Offer, Requisition
from .services import (
    FollowUpError,
    NoSupervisor,
    StaleCall,
    bulk_move,
    bulk_reassign,
    cancel,
    edit_call_log,
    log_call,
    reassign,
    reschedule,
    schedule_call,
    snooze_call,
    visible_followups,
)
from .whereabouts import parse_day

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
WHENS = [("overdue", "Overdue"), ("today", "Due today"), ("later", "Later")]
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
        # The latest status someone wrote: a quick call without one doesn't blank it.
        last_status=Subquery(
            CallLog.objects.filter(person=person, not_a_call=False)
            .exclude(notes="")
            .values("notes")[:1]
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
    if day := parse_day(get.get("due_from")):
        rows = rows.filter(due__date__gte=day)
    if day := parse_day(get.get("due_to")):
        rows = rows.filter(due__date__lte=day)
    today = timezone.localdate()
    when = get.get("when")
    if when == "overdue":
        rows = rows.filter(due__date__lt=today)
    elif when == "today":
        rows = rows.filter(due__date=today)
    elif when == "later":
        rows = rows.filter(due__date__gt=today)
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
        rows = rows.filter(dept__in=departments)
    if subs := get.getlist("sub"):
        rows = rows.filter(sub__in=subs)
    if priorities := get.getlist("priority"):
        rows = rows.filter(person__priority__in=priorities)
    if contacts := get.getlist("contact"):
        rows = rows.filter(person__contact_status__in=contacts)
    if get.get("owner", "").isdigit():
        rows = rows.filter(owner_id=get["owner"])
    elif get.get("owner") == "none":
        rows = rows.filter(owner__isnull=True)
    if phone := get.get("phone", "").strip():
        match = Q(person__phone__icontains=phone)
        if digits := phone_key(phone):  # spaces and +91 differ between spellings
            match |= Q(person__phone_key__contains=digits)
        rows = rows.filter(match)
    if status := get.get("status", "").strip():
        rows = rows.filter(last_status__icontains=status)
    if day := parse_day(get.get("lead_from")):
        rows = rows.filter(person__lead_received_on__gte=day)
    if day := parse_day(get.get("lead_to")):
        rows = rows.filter(person__lead_received_on__lte=day)
    return rows


def _dept_data(base, get):
    """What the department filters offer: each department with its sub-departments
    (the fixed list plus any other value typed on a requisition), and what is ticked."""
    typed = {}
    for dept, name in base.values_list("dept", "sub").distinct():
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
        ({**r, "owner": owners.get(r["owner"])} for r in per_owner),
        key=lambda r: -(r["today"] + r["overdue"]),
    )
    return {
        "today": sum(r["today"] for r in by_owner),
        "overdue": sum(r["overdue"] for r in by_owner),
        "interview": sum(r["interview"] for r in by_owner),
        "offer": sum(r["offer"] for r in by_owner),
        "people": sum(1 for r in by_owner if r["owner"]),  # Unassigned is not a person
        "by_owner": by_owner,
    }


@section
def screening(request):
    base = visible_followups(request.user, request.companies)
    tags = dict(TAGS)
    page = paginate(request, _sheet(base, request.GET))
    rows = list(page)
    for f in rows:
        f.tag_label = tags.get(f.last_tag or "none")
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
            "get": request.GET,
            "picked": {k: request.GET.getlist(k) for k in ("purpose", "tag", "stage")},
            "dept_data": _dept_data(base, request.GET),
            "can_bulk": True,
            "can_assign": _can_reassign(request.user),
            "page_ids": [str(f.pk) for f in rows],
            "filters": _export_qs(request.GET),
            "assignees": ReassignForm(companies=request.companies)
            .fields["owner"]
            .queryset,
            "reasons": FollowUp.Reason.choices,
            "today": timezone.localdate().isoformat(),
            "filtered": _filtered(request.GET),
            "stages": STAGES,
            "priorities": Person.Priority.choices,
            "contacts": Person.ContactStatus.choices,
            "whens": WHENS,
        },
    )


def _filtered(get):
    return any(v for k, v in get.items() if k != "page")


def _export_qs(get):
    """The filters without the page number: what the Export link carries."""
    get = get.copy()
    get.pop("page", None)
    return get.urlencode()


def _mine(request):
    # A candidate I already called today is done for the day: their next
    # follow-up shows from its own date.
    called = CallLog.objects.filter(
        caller=request.user,
        not_a_call=False,
        called_at__date=timezone.localdate(),
        person=OuterRef("person"),
    )
    return (
        visible_followups(request.user, request.companies)
        .filter(owner=request.user, due__date=timezone.localdate())
        .exclude(Exists(called))
        # Interview and offer calls first, normal follow-ups last.
        .annotate(
            rank=Case(
                When(purpose__in=["interview", "offer"], then=0),
                default=1,
            )
        )
        .order_by("rank", "due", "id")
    )


@calling_section
def calling(request):
    tags = dict(TAGS)
    page = paginate(request, _sheet(_mine(request), request.GET))
    rows = list(page)
    for f in rows:
        f.tag_label = tags.get(f.last_tag or "none")
    return render(
        request,
        "hiring/calling.html",
        {
            "rows": rows,
            "page": page,
            "get": request.GET,
            "purposes": FollowUp.Purpose.choices,
            "tags": TAGS,
            "dept_data": _dept_data(_mine(request), request.GET),
            "filters": _export_qs(request.GET),
            "filtered": _filtered(request.GET),
        },
    )


@calling_section
@require_GET
def export_calling(request):
    return followups_workbook(_sheet(_mine(request), request.GET))


def _log_base(request):
    """The calls this user may see: their companies' real calls for admins and
    supervisors; for everyone else their own, plus every call on the candidates
    they currently hold a pending follow-up for."""
    logs = CallLog.objects.filter(
        person__company__in=request.companies, not_a_call=False
    )
    if _can_reassign(request.user):
        return logs
    mine = FollowUp.objects.filter(
        owner=request.user, status=FollowUp.Status.PENDING
    ).values("person")
    return logs.filter(Q(caller=request.user) | Q(person__in=mine))


# What the Yes/No filters on the page test.
LOG_FLAGS = {
    "rescheduled": ("Rescheduled", Q(rescheduled=True)),
    "department_changed": ("Department changed", Q(department_changed=True)),
    "discussed": ("Discuss with manager", Q(discussed=True)),
    "whereabout": (
        "Has a whereabout form",
        ~Q(mini_whereabout={}) | ~Q(major_whereabout={}),
    ),
}
# shortcut: the export holds the newest rows only, upgrade to a streamed file.
EXPORT_LIMIT = 5000


def _logs(request):
    """Every call, newest first, for admins and supervisors; narrowed by the
    from/to dates, caller, tag, type, flags and a name/phone search."""
    g = request.GET
    logs = (
        _log_base(request)
        .select_related("person", "caller")
        .order_by("-called_at", "-id")
    )
    start, end = parse_day(g.get("from")), parse_day(g.get("to"))
    if start and end and start > end:
        start, end = end, start
    if start:
        logs = logs.filter(called_at__date__gte=start)
    if end:
        logs = logs.filter(called_at__date__lte=end)
    caller = g.get("caller", "")
    if caller.isascii() and caller.isdigit() and len(caller) < 10:
        logs = logs.filter(caller_id=caller)
    if g.get("tag") in CallLog.Outcome.values:
        logs = logs.filter(outcome=g["tag"])
    if g.get("type") in CallLog.Kind.values:
        logs = logs.filter(call_type=g["type"])
    for name, (_, cond) in LOG_FLAGS.items():
        if g.get(name) == "1":
            logs = logs.filter(cond)
    q = g.get("q", "").strip()
    if q:
        match = Q(person__name__icontains=q) | Q(person__phone__icontains=q)
        digits = phone_key(q)
        if digits:
            match |= Q(person__phone_key__contains=digits)
        logs = logs.filter(match)
    return logs


@calling_section
@require_GET
def call_logs(request):
    # The filters picked last time come back until cleared (?clear=1).
    saved = request.session.get("call_log_filters")
    picked = request.GET.copy()
    picked.pop("page", None)
    if "clear" in picked:
        request.session.pop("call_log_filters", None)
        return redirect("hiring:call_logs")
    if picked:
        request.session["call_log_filters"] = picked.urlencode()
    elif saved:
        page_no = request.GET.get("page")
        extra = f"&page={page_no}" if page_no else ""
        return redirect(f"{reverse('hiring:call_logs')}?{saved}{extra}")
    logs = _logs(request)
    # Callers who appear in the unfiltered list, so the dropdown stays in scope.
    callers = (
        get_user_model()
        .objects.filter(pk__in=_log_base(request).values("caller"))
        .order_by("first_name", "username")
    )
    page = paginate(request, logs)
    rows = list(page)
    for c in rows:
        c.mini = whereabouts.summary(c.mini_whereabout)
        c.major = whereabouts.summary(c.major_whereabout)
    return render(
        request,
        "hiring/call_logs.html",
        {
            "rows": rows,
            "page": page,
            "callers": callers,
            "tags": CallLog.Outcome.choices,
            "kinds": CallLog.Kind.choices,
            "flags": [(k, v[0]) for k, v in LOG_FLAGS.items()],
            "export_limit": EXPORT_LIMIT,
            "can_edit_all": _can_reassign(request.user),
            "f": request.GET,
        },
    )


@calling_section
def call_log_edit(request, pk):
    log = get_object_or_404(_log_base(request), pk=pk)
    if not (_can_reassign(request.user) or log.caller_id == request.user.pk):
        raise PermissionDenied
    form = CallLogEditForm(request.POST or None, log=log)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            edit_call_log(
                log,
                request.user,
                d["version"],
                outcome=d["outcome"],
                notes=d["notes"],
                call_type=d["call_type"],
                rescheduled=d["rescheduled"],
                reschedule_reason=d["reschedule_reason"].strip(),
                department_changed=d["department_changed"],
                discuss=d["discuss"],
                mini_whereabout=d["mini_whereabout"],
                major_whereabout=d["major_whereabout"],
            )
        except NoSupervisor as e:
            form.add_error(None, str(e))
        except StaleCall as e:
            messages.error(request, str(e))
            return redirect("hiring:call_log_edit", pk=pk)
        else:
            messages.success(request, "Call updated.")
            return redirect("hiring:call_logs")
    return render(
        request,
        "hiring/call_log_edit.html",
        {"call_form": form, "call_action": request.path, "log": log, "editing": True},
    )


@calling_section
@require_GET
def export_call_logs(request):
    g = request.GET
    day = lambda k: parse_day(g.get(k))  # noqa: E731
    return call_logs_workbook(_logs(request)[:EXPORT_LIMIT], day("from"), day("to"))


@section
@require_POST
def bulk(request):
    """Assign, or move the date of, the ticked follow-ups or all a filter matches."""
    filters = QueryDict(request.POST.get("filters", ""))
    back = reverse("hiring:screening") + (f"?{filters.urlencode()}" if filters else "")
    form = BulkForm(request.POST, companies=request.companies)
    if not form.is_valid():
        error = next(iter(form.errors.values()))[0]
        if "preview" in request.POST:
            return HttpResponse(format_html('<p class="text-red-600">{}</p>', error))
        messages.error(request, error)
        return redirect(back)
    d = form.cleaned_data
    # visible_followups already limits a recruiter to their own calls, so moving
    # needs no extra right; handing calls to someone else does.
    if d["do"] == "assign" and not _can_reassign(request.user):
        raise PermissionDenied
    if "preview" in request.POST and d["do"] != "move":
        return HttpResponse(status=400)
    seen = visible_followups(request.user, request.companies)
    if d["scope"] == "all":
        seen = _sheet(seen, filters)
    else:
        ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
        seen = seen.filter(pk__in=ids)
    # shortcut: ids are loaded into Python; fine at a few thousand follow-ups.
    pks = list(seen.order_by().values_list("pk", flat=True))
    rows = FollowUp.objects.filter(pk__in=pks, status=FollowUp.Status.PENDING)
    if "preview" in request.POST:
        # The confirm dialog: who would move, nothing written yet.
        calls = rows.filter(purpose=FollowUp.Purpose.CALL).order_by("due", "pk")
        count = calls.count()
        return render(
            request,
            "hiring/_bulk_preview.html",
            {
                "rows": calls.select_related("person", "owner")[:100],
                "count": count,
                "skipped": len(pks) - count,
                "d": d,
                "ids": pks if d["scope"] == "ticked" else [],
                "filters": filters.urlencode(),
            },
        )
    if not pks:
        messages.error(request, "Nothing is selected.")
        return redirect(back)
    if d["do"] == "assign":
        n = bulk_reassign(rows, d["owner"], request.user)
        messages.success(
            request,
            f"Gave {n} follow-up{'s' if n != 1 else ''} to {d['owner'].display_name}.",
        )
    else:
        n = bulk_move(rows, d["day"], d["reason"], by=request.user)
        left = len(pks) - n
        note = (
            f" {left} interview, offer or joining dates were left as they are."
            if left
            else ""
        )
        if n:
            messages.success(
                request,
                f"Moved {n} call{'s' if n != 1 else ''} to {d['day']:%d/%m/%Y}.{note}",
            )
        else:
            messages.error(request, f"No calls to move.{note}")
    return redirect(back)


@section
@require_GET
def export_followups(request):
    rows = visible_followups(request.user, request.companies)
    return followups_workbook(_sheet(rows, request.GET))


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
        except NoSupervisor as exc:
            # Keep what was typed: a whereabout form is long.
            messages.error(request, str(exc))
            return _detail(request, followup, **{form_key: form})
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
        mini_whereabout=d["mini_whereabout"],
        major_whereabout=d["major_whereabout"],
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
