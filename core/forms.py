from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    SetPasswordForm,
)

from .models import User


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


class ResetPasswordForm(SetPasswordForm):
    """Choosing a password from the emailed link: now it's their own."""

    def save(self, commit=True):
        self.user.must_change_password = False
        return super().save(commit)


class ProfileForm(forms.ModelForm):
    """Name and email. Email doubles as the password-reset address, so changing it
    needs the current password."""

    current_password = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True

    def clean(self):
        cleaned = super().clean()
        if "email" in self.changed_data and "email" in cleaned:
            password = cleaned.get("current_password", "")
            if not self.instance.check_password(password):
                self.add_error(
                    "current_password",
                    "Enter your current password to change your email."
                    if not password
                    else "That isn't your current password. Try again.",
                )
        return cleaned
