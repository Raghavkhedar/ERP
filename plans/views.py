from datetime import date as make_date
from datetime import datetime

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .excel import schedule_rows
from .export import plans_workbook
from .models import PlanItem
from .services import (
    PlanError,
    add_block,
    agenda,
    can_view,
    day_panel,
    delete_blocks,
    is_set,
    move_blocks,
    plan_for,
    progress,
    rename_blocks,
    save_plan,
    toggle_goal,
)


def _rows(post):
    """The rows of the plan form, in the order the page sent them."""
    rows = []
    for key in post.getlist("row"):
        item_id = post.get(f"id_{key}", "")
        rows.append(
            (
                int(item_id) if item_id.isdigit() else None,
                post.get(f"kind_{key}", ""),
                post.get(f"text_{key}", ""),
                f"done_{key}" in post,
                _time(post.get(f"start_{key}")),
                _time(post.get(f"end_{key}")),
            )
        )
    return rows


def _time(value):
    try:
        return datetime.strptime(value or "", "%H:%M").time()
    except ValueError:
        return None


@login_required
def today(request):
    date = timezone.localdate()
    plan = plan_for(request.user, date)
    error = None
    rows = None
    imported = False
    if request.method == "POST" and "sheet" in request.FILES:
        # Fill the form from the sheet; nothing is saved until they press Save.
        try:
            lines = schedule_rows(request.FILES["sheet"])
        except PlanError as exc:
            error = str(exc)
        else:
            imported = True
            rows = [
                (None, kind, text, False, start, end)
                for kind, text, start, end in lines
            ]
            if not any(r[1] == PlanItem.Kind.GOAL for r in rows) and plan:
                rows = [
                    (i.pk, i.kind, i.text, i.done, i.starts_at, i.ends_at)
                    for i in plan.items.filter(kind=PlanItem.Kind.GOAL)
                ] + rows
    elif request.method == "POST":
        rows = _rows(request.POST)
        try:
            save_plan(request.user, date, rows)
        except PlanError as exc:
            error = str(exc)
        else:
            messages.success(request, "Plan saved.")
            return redirect("home")
    if rows is None:
        rows = [
            (i.pk, i.kind, i.text, i.done, i.starts_at, i.ends_at)
            for i in (plan.items.all() if plan else [])
        ]
    context = {
        "date": date,
        "rows": [
            {
                "id": r[0],
                "kind": r[1],
                "text": r[2],
                "done": r[3],
                "start": r[4].strftime("%H:%M") if r[4] else "",
                "end": r[5].strftime("%H:%M") if r[5] else "",
            }
            for r in rows
        ],
        "agenda": agenda(request.user, date),
        "locked": not is_set(plan),
        "error": error,
        "imported": imported,
        "goal": PlanItem.Kind.GOAL,
        "work": PlanItem.Kind.WORK,
    }
    return render(request, "plans/today.html", context)


@login_required
def view(request, user_id, year, month, day):
    owner = get_object_or_404(get_user_model(), pk=user_id)
    if not can_view(request.user, owner):
        raise PermissionDenied
    try:
        shown = make_date(year, month, day)
    except ValueError:
        raise Http404("No such day.") from None
    plan = plan_for(owner, shown)
    done, total = progress(plan)
    context = {
        "owner": owner,
        "day": shown,
        "plan": plan,
        "goals": plan.items.filter(kind=PlanItem.Kind.GOAL) if plan else [],
        "work": plan.items.filter(kind=PlanItem.Kind.WORK) if plan else [],
        "agenda": agenda(owner, shown),
        "done": done,
        "total": total,
    }
    return render(request, "plans/view.html", context)


def _day(value):
    """A ?from= / ?to= date, or None when it's missing or not a date."""
    try:
        return make_date.fromisoformat(value or "")
    except ValueError:
        return None


@login_required
@require_GET
def export_plans(request, user_id):
    """A person's plans as a spreadsheet, all of them or ?from= and ?to=."""
    owner = get_object_or_404(get_user_model(), pk=user_id)
    if not can_view(request.user, owner):
        raise PermissionDenied
    return plans_workbook(
        owner, _day(request.GET.get("from")), _day(request.GET.get("to"))
    )


@login_required
@require_GET
def panel(request):
    """The home page's "Your day" panel on its own, to refresh it after an edit."""
    today = timezone.localdate()
    return render(
        request, "plans/_day_panel.html", {"panel": day_panel(request.user, today)}
    )


@login_required
@require_POST
def block(request):
    """Create, move, rename or delete blocks on today's plan, for the timeline."""
    post, today = request.POST, timezone.localdate()
    ids = [int(i) for i in post.getlist("ids") if i.isdigit()]
    try:
        action = post.get("action")
        if action == "add":
            start = datetime.strptime(post.get("start", ""), "%H:%M").time()
            add_block(request.user, today, post.get("title", ""), start)
        elif action == "move":
            move_blocks(request.user, today, ids, int(post.get("delta", "")))
        elif action == "rename":
            rename_blocks(request.user, today, ids, post.get("title", ""))
        elif action == "toggle_goal":
            if not post.get("id", "").isdigit():
                raise PlanError("That goal is gone. Refresh and try again.")
            toggle_goal(request.user, today, int(post["id"]), post.get("done") == "1")
        elif action == "delete":
            delete_blocks(request.user, today, ids)
        else:
            raise PlanError("Unknown action.")
    except ValueError:
        return JsonResponse({"error": "That time wasn't right."}, status=400)
    except PlanError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"ok": True})
