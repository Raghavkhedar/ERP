"""The command bar's search: pages a person can open, then the candidates and
tasks that match what they typed. Everything is scoped like the pages it links to."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from core.access import companies_with_access, scope
from people.services import visible_people
from tasks.services import visible_tasks

# (label, url name, the Empanelment section it needs, or None for everyone)
PAGES = [
    ("Home", "home", None),
    ("Tasks", "tasks:list", None),
    ("Schedule", "meetings:schedule", None),
    ("Chat", "chat:conversation_list", None),
    ("Daily plan", "plans:today", None),
    ("Preparing", "hiring:list", "openings"),
    ("Sourcing", "hiring:sourcing", "candidates"),
    ("Screening", "hiring:screening", "candidates"),
    ("Selecting", "hiring:selecting", "candidates"),
    ("Hiring", "hiring:offers", "candidates"),
    ("On-Boarding", "hiring:onboarding", "candidates"),
    ("Report", "hiring:report", "openings"),
    ("Candidates", "people:list", "candidates"),
    ("New candidate", "people:new", "candidates"),
]
LIMIT = 5


def _can(user, section):
    return (
        section is None or companies_with_access(user, "recruitment", section).exists()
    )


@login_required
@require_GET
def command(request):
    q = request.GET.get("q", "").strip()
    results = [
        {"group": "Pages", "label": label, "hint": "", "url": reverse(name)}
        for label, name, section in PAGES
        if q.lower() in label.lower() and _can(request.user, section)
    ]
    if len(q) >= 2:
        people = scope(request, "recruitment", "candidates")
        if people:
            results += [
                {
                    "group": "Candidates",
                    "label": p.name,
                    "hint": p.phone,
                    "url": reverse("people:detail", args=[p.pk]),
                }
                for p in visible_people(people, q)[:LIMIT]
            ]
        results += [
            {
                "group": "Tasks",
                "label": t.title,
                "hint": t.assigned_to.display_name,
                "url": reverse("tasks:detail", args=[t.pk]),
            }
            for t in visible_tasks(request.user).filter(description__icontains=q)[
                :LIMIT
            ]
        ]
    return JsonResponse({"results": results})
