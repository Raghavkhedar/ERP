from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import timeline as task_timeline
from .forms import StatusForm, TaskForm
from .models import Status
from .services import (
    TaskError,
    allowed_statuses,
    assign,
    can_assign,
    set_status,
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


def _form_page(request, context):
    """The form alone for the dialog, or as its own page without JavaScript."""
    in_dialog = bool(request.headers.get("HX-Request"))
    template = "tasks/_task_form.html" if in_dialog else "tasks/task_form_page.html"
    return render(request, template, {**context, "in_dialog": in_dialog})


@login_required
def task_list(request):
    tasks = list(visible_tasks(request.user).exclude(status=Status.CLOSED))
    closed = (
        visible_tasks(request.user)
        .filter(status=Status.CLOSED)
        .order_by("-closed_at")[:20]
    )
    context = {
        "tasks": tasks,
        "closed": closed,
        "can_assign": can_assign(request.user),
    }
    return render(request, "tasks/list.html", context)


@login_required
def new_task(request):
    if not can_assign(request.user):
        raise PermissionDenied("Only admins assign tasks.")
    form = TaskForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            task = assign(
                request.user,
                data["assigned_to"],
                data["priority"],
                data["description"],
                data["due_date"],
            )
        except TaskError as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request, f"Task assigned to {task.assigned_to.display_name}."
            )
            return _done(request, _next(request, reverse("tasks:list")))
    context = {
        "form": form,
        "action": reverse("tasks:new"),
        "received": timezone.now(),
        "submit": "Assign task",
        "next": _next(request, ""),
    }
    return _form_page(request, context)


@login_required
def edit_task(request, pk):
    if not can_assign(request.user):
        raise PermissionDenied("Only admins change tasks.")
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    form = TaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Task saved.")
        return _done(request, reverse("tasks:detail", args=[task.pk]))
    context = {
        "form": form,
        "task": task,
        "action": reverse("tasks:edit", args=[task.pk]),
        "received": task.received_at,
        "submit": "Save changes",
    }
    return _form_page(request, context)


@login_required
def task_detail(request, pk):
    task = get_object_or_404(visible_tasks(request.user), pk=pk)
    context = {
        "task": task,
        "statuses": allowed_statuses(task, request.user),
        "can_assign": can_assign(request.user),
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


def timeline_context(request):
    today = timezone.localdate()
    start = task_timeline.parse_start(request.GET.get("from"), today)
    return {
        "timeline": task_timeline.build(request.user, start),
        "can_assign": can_assign(request.user),
    }


@login_required
def timeline(request):
    """The timeline alone, for moving it a week back or forward."""
    return render(request, "tasks/_timeline.html", timeline_context(request))
