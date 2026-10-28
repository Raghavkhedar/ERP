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
