from core.export import stamp, workbook_response

from .models import PlanItem


def plans_workbook(owner, start=None, end=None):
    """One person's plan items, a row each, newest day first."""
    items = PlanItem.objects.filter(plan__user=owner).select_related("plan")
    if start:
        items = items.filter(plan__date__gte=start)
    if end:
        items = items.filter(plan__date__lte=end)
    items = items.order_by("-plan__date", "kind", "position", "id")
    rows = [
        (
            i.plan.date,
            owner.display_name,
            i.get_kind_display(),
            i.text,
            "Yes" if i.done else "No",
            i.starts_at,
            i.ends_at,
        )
        for i in items
    ]
    return workbook_response(
        stamp(f"plans-{owner.username}"),
        {"Plan": (("Date", "Person", "Kind", "Item", "Done", "From", "To"), rows)},
    )
