from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, resolve_url
from django.urls import reverse


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


class ForcePasswordChangeMiddleware:
    """Send people to the change-password page until they have chosen their own.

    New accounts and accounts an admin reset start with a password someone else
    knows. Logging out and the change page itself stay reachable.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and user.must_change_password
            and request.path not in self.allowed_paths()
            and not request.path.startswith(settings.STATIC_URL)
        ):
            url = reverse("password_change")
            if request.headers.get("HX-Request"):
                return HttpResponse(status=204, headers={"HX-Redirect": url})
            return redirect(url)
        return self.get_response(request)

    @staticmethod
    def allowed_paths():
        return {reverse("password_change"), reverse("logout")}
