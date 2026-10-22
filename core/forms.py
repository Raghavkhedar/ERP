from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    # Django's default says both fields may be case-sensitive; employee IDs are not.
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": (
            "That employee ID and password don't match. Check them and try again."
        ),
    }
