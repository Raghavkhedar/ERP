from django.contrib import messages
from django.contrib.auth import get_user_model
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
from .forms import AlarmForm, StatusForm, TaskForm, UpdateForm
from .models import Attachment, Status
from .services import (
    TaskError,
    add_task_files,
    add_update,
    allowed_statuses,
    assign,
    can_assign,
    can_nudge,
    can_set_alarm,
    can_update,
    dismiss_alarm,
    due_alarms,
    next_alarm_in,
    nudge,
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
    session so it sticks across weeks and reloads. None means everyone.
    """
    if not can_assign(request.user):
        return {}
    if "person" in request.GET:
        request.session[PERSON_KEY] = request.GET["person"]
    chosen = str(request.session.get(PERSON_KEY, ""))
    people = (
        get_user_model()
        .objects.filter(is_active=True)
        .order_by("first_name", "last_name", "username")
    )
    person = people.filter(pk=chosen).first() if chosen.isdigit() else None
    return {"people": people, "person": person}


@login_required
def task_list(request):
    filtering = _person_filter(request)
    tasks = visible_tasks(request.user)
    if filtering.get("person"):
        tasks = tasks.filter(assigned_to=filtering["person"])
    context = {
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
    return tasks_workbook(tasks)


@login_required
def new_task(request):
    personal = not can_assign(request.user)
    form = TaskForm(request.POST or None, request.FILES or None, personal=personal)
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
    if not can_assign(request.user):
        raise PermissionDenied("Only admins change tasks.")
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    form = TaskForm(request.POST or None, request.FILES or None, instance=task)
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
        "can_assign": can_assign(request.user),
        "can_update": can_update(task, request.user),
        "can_nudge": can_nudge(task, request.user),
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


@login_required
@require_GET
def alarms(request):
    """The user's alarms that are ringing, polled by the popup on every page."""
    return JsonResponse(
        {
            "alarms": [
                {
                    "id": task.pk,
                    "title": task.title,
                    "url": reverse("tasks:detail", args=[task.pk]),
                    "action": reverse("tasks:alarm", args=[task.pk]),
                    "repeats": bool(task.remind_every),
                }
                for task in due_alarms(request.user)
            ],
            "next_in": next_alarm_in(request.user),
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
