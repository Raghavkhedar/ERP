from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.access import require_section
from core.pagination import paginate

from .export import offers_workbook, onboarding_workbook
from .forms import AcceptForm, DeclineForm, JoinedForm, RoundForm, StartOfferForm
from .services import (
    FollowUpError,
    accept,
    add_round,
    decline,
    did_not_join,
    mark_joined,
    offers_waiting,
    onboarding,
    start_offer,
    visible_interviews,
    visible_offers,
)

section = require_section("recruitment", "hiring")
onboarding_section = require_section("recruitment", "onboarding")


@section
def hiring(request):
    offers = visible_offers(request.companies)
    return render(
        request,
        "hiring/offers.html",
        {
            "interviews": visible_interviews(request.companies)[:100],
            "waiting": paginate(
                request,
                offers_waiting(request.user, request.companies),
                param="wpage",
            ),
            "open": paginate(request, offers.filter(state="offered"), param="opage"),
            "closed": offers.exclude(state="offered")[:100],
        },
    )


@section
@require_GET
def export_offers(request):
    return offers_workbook(visible_offers(request.companies))


@section
def begin(request, pk):
    followup = get_object_or_404(offers_waiting(request.user, request.companies), pk=pk)
    # Pre-filled with what the candidate expects, so it's usually one tap.
    form = StartOfferForm(
        request.POST or None, initial={"amount": followup.person.expected_salary}
    )
    if request.method == "POST" and form.is_valid():
        try:
            offer = start_offer(
                followup,
                form.cleaned_data["amount"],
                request.user,
                form.cleaned_data["note"],
            )
        except FollowUpError as exc:
            messages.error(request, str(exc))
            return redirect("hiring:offers")
        messages.success(request, "Offer made.")
        return redirect("hiring:offer", pk=offer.pk)
    return render(request, "hiring/offer_start.html", {"f": followup, "form": form})


def _offer(request, pk):
    return get_object_or_404(visible_offers(request.companies), pk=pk)


@section
def offer_detail(request, pk, forms=None):
    offer = _offer(request, pk)
    latest = offer.latest
    return render(
        request,
        "hiring/offer.html",
        {
            "offer": offer,
            "rounds": offer.rounds.select_related("by"),
            "round_form": (forms or {}).get("round_form")
            or RoundForm(initial={"amount": latest.counter or latest.amount}),
            "accept_form": (forms or {}).get("accept_form") or AcceptForm(),
            "decline_form": DeclineForm(),
        },
    )


def _act(request, pk, form_class, form_key, run, done):
    offer = _offer(request, pk)
    form = form_class(request.POST)
    if form.is_valid():
        try:
            run(offer, form.cleaned_data)
        except FollowUpError as exc:
            messages.error(request, str(exc))
            return redirect("hiring:offers")
        messages.success(request, done)
        return redirect("hiring:offer", pk=pk)
    return offer_detail(request, pk, {form_key: form})


@section
@require_POST
def new_round(request, pk):
    def run(o, d):
        add_round(o, d["amount"], request.user, d["counter"], d["note"])

    return _act(request, pk, RoundForm, "round_form", run, "Round added.")


@section
@require_POST
def accept_offer(request, pk):
    def run(o, d):
        accept(o, d["joining_date"], request.user)

    return _act(request, pk, AcceptForm, "accept_form", run, "Offer accepted.")


@section
@require_POST
def decline_offer(request, pk):
    def run(o, d):
        decline(o, d["reason"])

    return _act(request, pk, DeclineForm, "decline_form", run, "Offer declined.")


@onboarding_section
def onboarding_page(request):
    expecting, joined = onboarding(request.companies)
    return render(
        request,
        "hiring/onboarding.html",
        {"expecting": expecting, "joined": joined[:100], "form": JoinedForm()},
    )


@onboarding_section
@require_POST
def joined(request, pk):
    offer = _offer(request, pk)
    form = JoinedForm(
        request.POST,
        floor=offer.decided_at and timezone.localtime(offer.decided_at).date(),
    )
    if form.is_valid():
        try:
            d = form.cleaned_data
            mark_joined(
                offer,
                d["joined_on"],
                d["resources"],
                d["sim_allotted"],
                d["notes"],
            )
        except FollowUpError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Marked as joined.")
    else:
        for errors in form.errors.values():
            messages.error(request, errors[0])
    return redirect("hiring:onboarding")


@onboarding_section
@require_POST
def not_joined(request, pk):
    try:
        did_not_join(_offer(request, pk), request.POST.get("reason", "").strip()[:150])
    except FollowUpError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Marked as not joined.")
    return redirect("hiring:onboarding")


@onboarding_section
@require_GET
def export_onboarding(request):
    return onboarding_workbook(*onboarding(request.companies))
