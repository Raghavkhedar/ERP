from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .export import red_flags_workbook
from .forms import AssignForm, NoteForm, RedFlagForm, StatusForm
from .models import Attachment, Status
from .services import (
    RedFlagError,
    add_note,
    assign_to_supervisor,
    can_read,
    has_access,
    set_status,
    submit,
    supervisor_of,
    unassign,
    visible_flags,
)

FILTERS = {"open": "Open", "closed": "Closed", "all": "All"}


def _require_reader(user):
    # A 404, not a 403: nobody else should learn that red flags are read here.
    # Superadmins, and supervisors holding an assigned flag, get in.
    if not has_access(user):
        raise Http404


def _require_superadmin(user):
    if not can_read(user):
        raise Http404


def _detail(request, flag, note_form, status_form=None):
    context = {
        "flag": flag,
        "notes": flag.notes.select_related("author"),
        "files": flag.attachments.all(),
        "note_form": note_form,
        "status_form": status_form or StatusForm(initial={"status": flag.status}),
        "is_superadmin": can_read(request.user),
        "supervisors": {
            "against": supervisor_of(flag, "against"),
            "raiser": supervisor_of(flag, "raiser"),
        },
    }
    return render(request, "redflags/detail.html", context)


@login_required
def new_red_flag(request):
    form = RedFlagForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        submit(
            request.user,
            data["raised_against"],
            data["incident_date"],
            data["incident"],
            data["files"],
        )
        if request.headers.get("HX-Request"):
            return render(request, "redflags/_sent.html", {"in_dialog": True})
        return redirect("redflags:sent")
    in_dialog = bool(request.headers.get("HX-Request"))
    template = "redflags/_form.html" if in_dialog else "redflags/form_page.html"
    return render(request, template, {"form": form, "in_dialog": in_dialog})


@login_required
def sent(request):
    return render(request, "redflags/sent.html", {"in_dialog": False})


def _shown(request):
    """The flags the list is showing: (?show=) applied to what you may read."""
    _require_reader(request.user)
    chosen = request.GET.get("show", "open")
    items = visible_flags(request.user)
    if chosen == "open":
        items = items.filter(status=Status.OPEN)
    elif chosen == "closed":
        items = items.filter(status=Status.CLOSED)
    else:
        chosen = "all"
    return chosen, items


@login_required
@require_GET
def export_red_flags(request):
    _, items = _shown(request)
    return red_flags_workbook(items)


@login_required
def red_flag_list(request):
    chosen, items = _shown(request)
    return render(
        request,
        "redflags/list.html",
        {"items": items, "filters": FILTERS, "chosen": chosen},
    )


@login_required
def red_flag_detail(request, pk):
    _require_reader(request.user)
    flag = get_object_or_404(visible_flags(request.user), pk=pk)
    return _detail(request, flag, NoteForm())


@login_required
@require_POST
def new_note(request, pk):
    _require_reader(request.user)
    flag = get_object_or_404(visible_flags(request.user), pk=pk)
    form = NoteForm(request.POST)
    if form.is_valid():
        note = add_note(flag, request.user, form.cleaned_data["body"])
        return redirect(reverse("redflags:detail", args=[flag.pk]) + f"#note-{note.pk}")
    return _detail(request, flag, form)


@login_required
@require_POST
def change_status(request, pk):
    _require_superadmin(request.user)
    flag = get_object_or_404(visible_flags(request.user), pk=pk)
    form = StatusForm(request.POST)
    if form.is_valid():
        try:
            set_status(flag, request.user, form.cleaned_data["status"])
        except RedFlagError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Saved.")
    return redirect("redflags:detail", pk=flag.pk)


@login_required
@require_POST
def assign(request, pk):
    _require_superadmin(request.user)
    flag = get_object_or_404(visible_flags(request.user), pk=pk)
    form = AssignForm(request.POST)
    if form.is_valid():
        try:
            assign_to_supervisor(flag, request.user, form.cleaned_data["of"])
        except RedFlagError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Assigned to {flag.assigned_to.display_name}.")
    return redirect("redflags:detail", pk=flag.pk)


@login_required
@require_POST
def remove_assignment(request, pk):
    _require_superadmin(request.user)
    flag = get_object_or_404(visible_flags(request.user), pk=pk)
    unassign(flag, request.user)
    messages.success(request, "Assignment removed.")
    return redirect("redflags:detail", pk=flag.pk)


@login_required
def attachment(request, pk):
    _require_reader(request.user)
    file = get_object_or_404(
        Attachment.objects.filter(red_flag__in=visible_flags(request.user)), pk=pk
    )
    return FileResponse(
        file.file.open("rb"),
        as_attachment=not file.is_image,
        filename=file.original_name,
    )
