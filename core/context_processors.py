from django.utils import timezone

from core.access import selected_company, user_companies


def company_switcher(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    companies = list(user_companies(user))
    return {
        "switcher_companies": companies,
        "current_company": selected_company(request) if companies else None,
    }


def time_requests(request):
    """How many people are waiting for the user to answer a request for their time."""
    if not request.user.is_authenticated:
        return {}

    def waiting():
        from meetings.models import SlotRequest

        return SlotRequest.objects.filter(
            slot__host=request.user,
            status=SlotRequest.Status.PENDING,
            slot__cancelled_at__isnull=True,
            slot__ends_at__gt=timezone.now(),
        ).count()

    return {"waiting_time_requests": waiting}
