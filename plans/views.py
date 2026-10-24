from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import PlanItem
from .services import PlanError, agenda, is_set, plan_for, save_plan


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
            )
        )
    return rows


@login_required
def today(request):
    date = timezone.localdate()
    plan = plan_for(request.user, date)
    error = None
    rows = None
    if request.method == "POST":
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
            (i.pk, i.kind, i.text, i.done) for i in (plan.items.all() if plan else [])
        ]
    context = {
        "date": date,
        "rows": [{"id": r[0], "kind": r[1], "text": r[2], "done": r[3]} for r in rows],
        "agenda": agenda(request.user, date),
        "locked": not is_set(plan),
        "error": error,
        "goal": PlanItem.Kind.GOAL,
        "work": PlanItem.Kind.WORK,
    }
    return render(request, "plans/today.html", context)
