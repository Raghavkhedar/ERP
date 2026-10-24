from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm


class LoginForm(AuthenticationForm):
    # Django's default says both fields may be case-sensitive; employee IDs are not.
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": (
            "That employee ID and password don't match. Check them and try again."
        ),
    }


class ChangePasswordForm(PasswordChangeForm):
    error_messages = {
        **PasswordChangeForm.error_messages,
        "password_incorrect": "That isn't your current password. Try again.",
        "same_password": "Choose a password different from your current one.",
    }

    def clean_new_password1(self):
        password = self.cleaned_data["new_password1"]
        if self.user.check_password(password):
            raise forms.ValidationError(
                self.error_messages["same_password"], code="same_password"
            )
        return password

    def save(self, commit=True):
        self.user.must_change_password = False
        return super().save(commit)
