from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import resolve_url


class HtmxLoginRedirectMiddleware:
    """Reload the whole page when an htmx request is sent to the login page.

    Without this, an expired session makes a poll swap the login form into
    the middle of the page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        login_url = resolve_url(settings.LOGIN_URL)
        if (
            request.headers.get("HX-Request")
            and response.status_code == 302
            and response.url.startswith(login_url)
        ):
            return HttpResponse(status=204, headers={"HX-Refresh": "true"})
        return response
