from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import timeline as task_timeline
from .export import tasks_workbook
from .forms import AlarmForm, DateChangeForm, StatusForm, TaskForm, UpdateForm
from .models import Attachment, Status
from .services import (
    TaskError,
    add_task_files,
    add_update,
    allowed_statuses,
    assign,
    assignable_people,
    can_assign,
    can_nudge,
    can_reschedule,
    can_set_alarm,
    can_update,
    dismiss_alarm,
    dismiss_all_alarms,
    due_alarms,
    manages,
    next_alarm_in,
    nudge,
    reschedule,
    set_alarm,
    set_status,
    snooze_alarm,
    updatable_tasks,
    visible_tasks,
)


def _done(request, url):
    """Leave the form: reload the page behind the dialog, or go to the url."""
    if request.headers.get("HX-Request"):
        return HttpResponse(headers={"HX-Redirect": url})
    return redirect(url)


def _next(request, default):
    """Where to go after the form: the page it was opened from, if it's ours."""
    url = request.POST.get("next") or request.GET.get("next")
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return default


def _form_page(request, context, form="tasks/_task_form.html"):
    """The form alone for the dialog, or as its own page without JavaScript."""
    in_dialog = bool(request.headers.get("HX-Request"))
    template = form if in_dialog else "tasks/form_page.html"
    return render(
        request, template, {**context, "in_dialog": in_dialog, "form_template": form}
    )


PERSON_KEY = "tasks_person"


def _person_filter(request):
    """The one person an assigner chose to see (?person=), remembered in the
    session so it sticks across weeks and reloads. None means everyone they can
    see.
    """
    if not can_assign(request.user):
        return {}
    if "person" in request.GET:
        request.session[PERSON_KEY] = request.GET["person"]
    chosen = str(request.session.get(PERSON_KEY, ""))
    people = assignable_people(request.user)
    person = people.filter(pk=chosen).first() if chosen.isdigit() else None
    return {"people": people, "person": person}


DUE_CHOICES = [
    ("", "Any due date"),
    ("overdue", "Overdue"),
    ("0", "Due today"),
    ("3", "Due in 3 days"),
    ("7", "Due in 7 days"),
    ("30", "Due in 30 days"),
]


def _due_filter(tasks, request):
    """?due=N: due from today through N days ahead; ?due=overdue: late ones."""
    due = request.GET.get("due", "")
    today = timezone.localdate()
    if due == "overdue":
        return tasks.filter(due_date__lt=today), due
    if due in ("0", "3", "7", "30"):
        end = today + timedelta(days=int(due))
        return tasks.filter(due_date__gte=today, due_date__lte=end), due
    return tasks, ""


STATUS_CHOICES = [("", "All statuses"), *Status.choices]


def _status_filter(tasks, request):
    """?status=open|ongoing|done|closed; anything else means all."""
    status = request.GET.get("status", "")
    if status in Status.values:
        return tasks.filter(status=status), status
    return tasks, ""


@login_required
def task_list(request):
    filtering = _person_filter(request)
    tasks = visible_tasks(request.user)
    if filtering.get("person"):
        tasks = tasks.filter(assigned_to=filtering["person"])
    tasks, due = _due_filter(tasks, request)
    tasks, status = _status_filter(tasks, request)
    context = {
        "status": status,
        "status_choices": STATUS_CHOICES,
        "due": due,
        "due_choices": DUE_CHOICES,
        "tasks": list(tasks.exclude(status=Status.CLOSED)),
        "closed": tasks.filter(status=Status.CLOSED).order_by("-closed_at")[:20],
        "can_assign": can_assign(request.user),
        **filtering,
    }
    return render(request, "tasks/list.html", context)


@login_required
@require_GET
def export_tasks(request):
    """The task list as a spreadsheet: the same tasks, open and closed."""
    tasks = visible_tasks(request.user)
    person = _person_filter(request).get("person")
    if person:
        tasks = tasks.filter(assigned_to=person)
    tasks = _due_filter(tasks, request)[0]
    return tasks_workbook(_status_filter(tasks, request)[0])


@login_required
def new_task(request):
    personal = not can_assign(request.user)
    form = TaskForm(
        request.POST or None,
        request.FILES or None,
        people=None if personal else assignable_people(request.user),
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            task = assign(
                request.user,
                request.user if personal else data["assigned_to"],
                data["priority"],
                data["description"],
                data["due_date"],
                data["files"],
                data["remind_at"],
                data["remind_every"],
            )
        except TaskError as error:
            form.add_error(None, str(error))
        else:
            if task.assigned_to == request.user:
                messages.success(request, "Task added.")
            else:
                messages.success(
                    request, f"Task assigned to {task.assigned_to.display_name}."
                )
            return _done(request, _next(request, reverse("tasks:list")))
    context = {
        "form": form,
        "action": reverse("tasks:new"),
        "received": timezone.now(),
        "heading": "Add a task for yourself" if personal else "Assign a task",
        "submit": "Add task" if personal else "Assign task",
        "next": _next(request, ""),
    }
    return _form_page(request, context)


@login_required
def edit_task(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    if not manages(request.user, task):
        raise PermissionDenied("Only admins and supervisors change tasks.")
    form = TaskForm(
        request.POST or None,
        request.FILES or None,
        instance=task,
        people=assignable_people(request.user),
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        add_task_files(task, request.user, form.cleaned_data["files"])
        messages.success(request, "Task saved.")
        return _done(request, reverse("tasks:detail", args=[task.pk]))
    context = {
        "form": form,
        "task": task,
        "action": reverse("tasks:edit", args=[task.pk]),
        "received": task.received_at,
        "heading": "Edit task",
        "submit": "Save changes",
    }
    return _form_page(request, context)


@login_required
def task_detail(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    updates = task.updates.select_related("author").prefetch_related("attachments")
    context = {
        "task": task,
        "files": task.attachments.all(),
        "updates": updates,
        "statuses": allowed_statuses(task, request.user),
        "can_manage": manages(request.user, task),
        "can_update": can_update(task, request.user),
        "can_nudge": can_nudge(task, request.user),
        "can_reschedule": can_reschedule(task, request.user),
        "date_form": DateChangeForm(initial={"due_date": task.due_date}),
        "date_changes": task.date_changes.select_related("changed_by"),
        "can_set_alarm": can_set_alarm(task, request.user),
        "alarm_form": AlarmForm(
            initial={"remind_at": task.remind_at, "remind_every": task.remind_every}
        ),
        "today": timezone.localdate(),
    }
    return render(request, "tasks/detail.html", context)


@login_required
@require_POST
def change_status(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    form = StatusForm(request.POST)
    if form.is_valid():
        try:
            task = set_status(task, request.user, form.cleaned_data["status"])
        except TaskError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Marked {task.get_status_display()}.")
    return redirect("tasks:detail", pk=task.pk)


@login_required
@require_POST
def change_date(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    form = DateChangeForm(request.POST)
    if form.is_valid():
        try:
            reschedule(
                task,
                request.user,
                form.cleaned_data["due_date"],
                form.cleaned_data["reason"],
            )
        except TaskError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Completion date changed.")
    else:
        for errors in form.errors.values():
            messages.error(request, errors[0])
    return redirect("tasks:detail", pk=task.pk)


@login_required
@require_POST
def nudge_task(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    try:
        nudge(task, request.user)
    except TaskError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Reminder sent.")
    return redirect("tasks:detail", pk=task.pk)


@login_required
@require_POST
def task_alarm(request, pk):
    """Set, clear, snooze or stop a task's alarm; JSON for the popup, else back."""
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    action = request.POST.get("action", "set")
    try:
        if action == "snooze":
            snooze_alarm(task, request.user, request.POST.get("length", ""))
        elif action == "dismiss":
            dismiss_alarm(task, request.user)
        else:
            form = AlarmForm(request.POST if action == "set" else None)
            if action == "set" and not form.is_valid():
                raise TaskError("Pick a valid date and time for the alarm.")
            data = form.cleaned_data if action == "set" else {}
            set_alarm(
                task, request.user, data.get("remind_at"), data.get("remind_every", "")
            )
            messages.success(
                request, "Alarm set." if data.get("remind_at") else "Alarm cleared."
            )
    except TaskError as error:
        if request.headers.get("Accept") == "application/json":
            return JsonResponse({"error": str(error)}, status=400)
        messages.error(request, str(error))
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"ok": True})
    return redirect("tasks:detail", pk=task.pk)


SHOWN_ALARMS = 5


@login_required
@require_POST
def dismiss_all(request):
    dismiss_all_alarms(request.user)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def alarms(request):
    """The user's alarms that are ringing, polled by the popup on every page:
    due tasks, and due calls and interviews from Empanelment."""
    # Imported here: hiring already imports from tasks.
    from hiring.services import due_call_alarms, next_call_alarm_in

    user = request.user
    tasks = list(due_alarms(user))
    calls = due_call_alarms(user)
    # Show a handful; the rest ring as these are dealt with. "Dismiss all" clears them.
    shown = max(SHOWN_ALARMS - len(tasks), 0)
    total = len(tasks) + calls.count()
    tasks = tasks[:SHOWN_ALARMS]
    rings = [
        {
            "id": task.pk,
            "title": task.title,
            "url": reverse("tasks:detail", args=[task.pk]),
            "action": reverse("tasks:alarm", args=[task.pk]),
            "repeats": bool(task.remind_every),
        }
        for task in tasks
    ] + [
        {
            "id": f"call-{f.pk}",
            "label": f"{f.get_purpose_display()} alarm",
            "title": f"{f.get_purpose_display()} {f.person.name}",
            "url": reverse("hiring:followup", args=[f.pk]),
            "action": reverse("hiring:followup_snooze", args=[f.pk]),
            "repeats": True,
        }
        for f in calls[:shown]
    ]
    waits = [next_alarm_in(user), next_call_alarm_in(user)]
    return JsonResponse(
        {
            "alarms": rings,
            "total": total,
            "next_in": min((w for w in waits if w is not None), default=None),
        }
    )


@login_required
def new_update(request):
    tasks = updatable_tasks(request.user)
    only = tasks[:2]
    initial = {
        "task": request.GET.get("task") or (only[0].pk if len(only) == 1 else None)
    }
    form = UpdateForm(
        request.POST or None, request.FILES or None, tasks=tasks, initial=initial
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            update = add_update(data["task"], request.user, data["body"], data["files"])
        except TaskError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f"Update added to {update.task.title}.")
            return _done(
                request, _next(request, reverse("tasks:detail", args=[update.task_id]))
            )
    context = {
        "form": form,
        "action": reverse("tasks:update_new"),
        "heading": "Add an update",
        "submit": "Add update",
        "today": timezone.localdate(),
        "next": _next(request, ""),
    }
    return _form_page(request, context, form="tasks/_update_form.html")


@login_required
def attachment(request, pk):
    file = get_object_or_404(
        Attachment.objects.filter(
            Q(task__in=visible_tasks(request.user))
            | Q(update__task__in=visible_tasks(request.user))
        ),
        pk=pk,
    )
    return FileResponse(
        file.file.open("rb"),
        as_attachment=not file.is_image,
        filename=file.original_name,
    )


def timeline_context(request):
    today = timezone.localdate()
    start = task_timeline.parse_start(request.GET.get("from"), today)
    filtering = _person_filter(request)
    return {
        "timeline": task_timeline.build(request.user, start, filtering.get("person")),
        "can_assign": can_assign(request.user),
        "can_log": updatable_tasks(request.user).exists(),
        **filtering,
    }


@login_required
def timeline(request):
    """The timeline alone, for moving it a week back or forward."""
    return render(request, "tasks/_timeline.html", timeline_context(request))
