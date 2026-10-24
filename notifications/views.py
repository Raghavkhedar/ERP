from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import services


@login_required
@require_GET
def pulse(request):
    """Unread count and anything newer than `after`, for the bell and popups."""
    after = request.GET.get("after", "")
    user = request.user
    items = services.since(user, int(after)) if after.isdigit() else []
    return JsonResponse(
        {
            "unread": services.unread_count(user),
            "latest": services.latest_id(user),
            "items": [
                {
                    "id": n.id,
                    "text": n.text,
                    "url": reverse("notifications:open", args=[n.pk]),
                }
                for n in items
            ],
        }
    )


@login_required
@require_GET
def dropdown(request):
    return render(
        request,
        "notifications/_list.html",
        {"notifications": services.recent(request.user)},
    )


@login_required
@require_GET
def open_notification(request, pk):
    """Mark it read, then go where it points (only ever somewhere on this site)."""
    notification = services.mark_read(request.user, pk)
    if notification is None:
        raise Http404("No such notification.")
    target = notification.url
    if not target or not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = reverse("home")
    return redirect(target)


@login_required
@require_POST
def read_all(request):
    services.mark_all_read(request.user)
    return render(
        request,
        "notifications/_list.html",
        {"notifications": services.recent(request.user)},
    )
