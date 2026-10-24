from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ConferenceForm, InviteMoreForm
from .models import Invitation
from .services import (
    SlotError,
    add_invitees,
    cancel_conference,
    conference_clashes,
    create_conference,
    live_conferences,
    remove_invitee,
    respond,
)


def _visible(user):
    """Live conferences the user hosts or is invited to."""
    return (
        live_conferences().filter(Q(host=user) | Q(invitations__user=user)).distinct()
    )


def _get(request, pk):
    conference = get_object_or_404(_visible(request.user).select_related("host"), pk=pk)
    invitation = conference.invitations.filter(user=request.user).first()
    conference.my_invitation = invitation
    conference.i_am_host = conference.host_id == request.user.pk
    return conference


@login_required
def conferences(request):
    now = timezone.now()
    upcoming = _visible(request.user).filter(ends_at__gt=now).select_related("host")
    hosting, waiting, going = [], [], []
    for conference in upcoming:
        if conference.host_id == request.user.pk:
            conference.count = conference.invitations.filter(
                status=Invitation.Status.ACCEPTED
            ).count()
            hosting.append(conference)
            continue
        status = conference.invitations.get(user=request.user).status
        if status == Invitation.Status.INVITED:
            waiting.append(conference)
        elif status == Invitation.Status.ACCEPTED:
            going.append(conference)
    context = {"hosting": hosting, "waiting": waiting, "going": going}
    return render(request, "meetings/conferences.html", context)


@login_required
def conference_new(request):
    form = ConferenceForm(request.POST or None, host=request.user)
    clashes = []
    if request.method == "POST" and form.is_valid():
        start, end = form.times()
        people = list(form.cleaned_data["invitees"])
        clashes = conference_clashes([request.user, *people], start, end)
        if clashes and "confirm" not in request.POST:
            pass  # show the warning; the host can still go ahead
        else:
            try:
                conference = create_conference(
                    request.user,
                    form.cleaned_data["title"],
                    start,
                    end,
                    people,
                    agenda=form.cleaned_data["agenda"],
                    location=form.cleaned_data["location"],
                )
            except SlotError as error:
                form.add_error(None, str(error))
                clashes = []
            else:
                messages.success(request, "Conference created. Invitations sent.")
                return redirect("meetings:conference_detail", pk=conference.pk)
    return render(
        request, "meetings/conference_new.html", {"form": form, "clashes": clashes}
    )


@login_required
def conference_detail(request, pk):
    conference = _get(request, pk)
    invitations = list(conference.invitations.select_related("user"))
    context = {
        "conference": conference,
        "invitations": invitations,
        "invite_form": InviteMoreForm(conference=conference)
        if conference.i_am_host
        else None,
        "over": conference.ends_at <= timezone.now(),
    }
    return render(request, "meetings/conference_detail.html", context)


@login_required
@require_POST
def conference_respond(request, pk):
    conference = _get(request, pk)
    accept = request.POST.get("answer") == "accept"
    try:
        respond(conference, request.user, accept)
    except SlotError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request, "You're going." if accept else "Declined. The host has been told."
        )
    return redirect("meetings:conference_detail", pk=pk)


@login_required
@require_POST
def conference_cancel(request, pk):
    conference = _get(request, pk)
    try:
        cancel_conference(conference, request.user)
    except SlotError as error:
        messages.error(request, str(error))
        return redirect("meetings:conference_detail", pk=pk)
    messages.success(request, "Conference cancelled. Everyone invited has been told.")
    return redirect("meetings:conferences")


@login_required
@require_POST
def conference_invite(request, pk):
    conference = _get(request, pk)
    form = InviteMoreForm(request.POST, conference=conference)
    if form.is_valid():
        try:
            added = add_invitees(
                conference, request.user, form.cleaned_data["invitees"]
            )
        except SlotError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Invited {len(added)} more.")
    else:
        messages.error(request, "Pick at least one person to invite.")
    return redirect("meetings:conference_detail", pk=pk)


@login_required
@require_POST
def conference_remove(request, pk, user_id):
    conference = _get(request, pk)
    person = get_object_or_404(get_user_model(), pk=user_id)
    try:
        remove_invitee(conference, request.user, person)
    except SlotError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Removed {person.display_name}.")
    return redirect("meetings:conference_detail", pk=pk)
