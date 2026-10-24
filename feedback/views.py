from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CommentForm, FeedbackForm, LessonForm, ResolutionForm
from .models import Area, Attachment, Feedback, Lesson, Status
from .services import (
    FeedbackError,
    add_comment,
    is_reader,
    save_lesson,
    search_lessons,
    set_resolution,
    submit,
    visible_feedback,
)

FILTERS = {
    "open": "Open",
    "resolved": "Resolved",
    "all": "All",
}


def _done(request, url):
    if request.headers.get("HX-Request"):
        return HttpResponse(headers={"HX-Redirect": url})
    return redirect(url)


def _page(request):
    """The page the form was opened from, if it's ours."""
    url = request.POST.get("page") or request.GET.get("page") or ""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return ""


def _guess_area(url):
    try:
        app = resolve(url.split("?")[0]).app_name
    except Resolver404:
        return Area.OTHER
    return app if app in Area.values else Area.OTHER


def _require_reader(user):
    if not is_reader(user):
        raise PermissionDenied("Only admins and trainers use lessons.")


def _detail(request, feedback, form, resolution=None):
    reader = is_reader(request.user)
    if reader and resolution is None:
        resolution = ResolutionForm(
            initial={"status": feedback.status, "outcome": feedback.outcome}
        )
    context = {
        "resolution": resolution,
        "lessons": feedback.lessons.all() if reader else [],
        "feedback": feedback,
        "comments": feedback.comments.select_related("author").prefetch_related(
            "attachments"
        ),
        "files": feedback.attachments.all(),
        "form": form,
        "is_reader": is_reader(request.user),
    }
    return render(request, "feedback/detail.html", context)


@login_required
def feedback_list(request):
    chosen = request.GET.get("show", "open")
    items = visible_feedback(request.user)
    if chosen == "open":
        items = items.exclude(status=Status.RESOLVED)
    elif chosen == "resolved":
        items = items.filter(status=Status.RESOLVED)
    else:
        chosen = "all"
    context = {
        "items": items,
        "filters": FILTERS,
        "chosen": chosen,
        "is_reader": is_reader(request.user),
    }
    return render(request, "feedback/list.html", context)


@login_required
def new_feedback(request):
    page = _page(request)
    form = FeedbackForm(
        request.POST or None,
        request.FILES or None,
        initial={"area": _guess_area(page)} if page else None,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        feedback = submit(
            request.user,
            data["kind"],
            data["area"],
            data["message"],
            page,
            data["files"],
        )
        messages.success(
            request, "Thank you, your feedback was sent to the admins and trainers."
        )
        return _done(request, reverse("feedback:detail", args=[feedback.pk]))
    in_dialog = bool(request.headers.get("HX-Request"))
    template = "feedback/_form.html" if in_dialog else "feedback/form_page.html"
    return render(
        request, template, {"form": form, "page": page, "in_dialog": in_dialog}
    )


@login_required
def feedback_detail(request, pk):
    feedback = get_object_or_404(visible_feedback(request.user), pk=pk)
    return _detail(request, feedback, CommentForm())


@login_required
@require_POST
def new_comment(request, pk):
    feedback = get_object_or_404(visible_feedback(request.user), pk=pk)
    form = CommentForm(request.POST, request.FILES)
    if form.is_valid():
        comment = add_comment(
            feedback,
            request.user,
            form.cleaned_data["body"],
            form.cleaned_data["files"],
        )
        return redirect(
            reverse("feedback:detail", args=[feedback.pk]) + f"#comment-{comment.pk}"
        )
    return _detail(request, feedback, form)


@login_required
def attachment(request, pk):
    file = get_object_or_404(
        Attachment.objects.filter(
            Q(feedback__in=visible_feedback(request.user))
            | Q(comment__feedback__in=visible_feedback(request.user))
        ),
        pk=pk,
    )
    return FileResponse(
        file.file.open("rb"),
        as_attachment=not file.is_image,
        filename=file.original_name,
    )


@login_required
@require_POST
def change_resolution(request, pk):
    feedback = get_object_or_404(visible_feedback(request.user), pk=pk)
    _require_reader(request.user)
    form = ResolutionForm(request.POST)
    if form.is_valid():
        try:
            set_resolution(
                feedback,
                request.user,
                form.cleaned_data["status"],
                form.cleaned_data["outcome"],
            )
        except FeedbackError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Saved.")
            return redirect("feedback:detail", pk=feedback.pk)
    return _detail(request, feedback, CommentForm(), resolution=form)


@login_required
def lesson_list(request):
    _require_reader(request.user)
    query = request.GET.get("q", "").strip()
    area = request.GET.get("area", "")
    if area not in Area.values:
        area = ""
    context = {
        "lessons": search_lessons(query, area),
        "query": query,
        "area": area,
        "areas": Area.choices,
    }
    return render(request, "feedback/lessons.html", context)


@login_required
def lesson_detail(request, pk):
    _require_reader(request.user)
    lesson = get_object_or_404(Lesson.objects.select_related("created_by"), pk=pk)
    context = {"lesson": lesson, "sources": lesson.feedback.select_related("submitter")}
    return render(request, "feedback/lesson_detail.html", context)


def _lesson_form(request, lesson=None):
    source = None
    linked = []
    initial = None
    # The form posts back to the same url, so ?feedback= is still here on save.
    wanted = request.GET.get("feedback", "")
    if lesson is None and wanted.isdigit():
        source = Feedback.objects.filter(pk=wanted).first()
    if source:
        linked = [source.pk]
    if source and request.method == "GET":
        initial = {
            "title": source.summary[:120],
            "area": source.area,
            "what_happened": source.message,
            "feedback": linked,
        }
    form = LessonForm(
        request.POST or None, instance=lesson, initial=initial, linked=linked
    )
    if request.method == "POST" and form.is_valid():
        saved = save_lesson(form, request.user)
        messages.success(request, "Lesson saved.")
        return redirect("feedback:lesson", pk=saved.pk)
    heading = "Edit lesson" if lesson else "Write a lesson"
    context = {"form": form, "heading": heading, "lesson": lesson}
    return render(request, "feedback/lesson_form.html", context)


@login_required
def new_lesson(request):
    _require_reader(request.user)
    return _lesson_form(request)


@login_required
def edit_lesson(request, pk):
    _require_reader(request.user)
    return _lesson_form(request, get_object_or_404(Lesson, pk=pk))
