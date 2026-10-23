import re

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords


class OfficeUserManager(UserManager):
    def get_by_natural_key(self, username):
        # Log in with "s123" as well as "S123".
        return super().get_by_natural_key(self.model.normalize_username(username))


class User(AbstractUser):
    # The username column holds the Employee ID: the login, never reused.
    # People are shown by display_name, not by this ID.
    username = models.CharField(
        "employee ID",
        max_length=150,
        unique=True,
        validators=[
            # Checked before saving turns "s123" into "S123": allow either case.
            RegexValidator(
                r"^S\d+\Z",
                "Employee IDs look like S123: an S, then digits.",
                flags=re.IGNORECASE,
            )
        ],
        help_text="Used to log in, for example S123.",
        error_messages={"unique": "Someone already has this employee ID."},
    )

    objects = OfficeUserManager()
    history = HistoricalRecords(excluded_fields=["password", "last_login"])

    class Meta(AbstractUser.Meta):
        constraints = [
            # Office mailboxes are handed on to the next person (a new intern
            # gets the old intern's address), so an email only identifies
            # someone while their account is active.
            models.UniqueConstraint(
                Lower("email"),
                condition=Q(is_active=True) & ~Q(email=""),
                name="core_user_unique_active_email",
                violation_error_message=(
                    "An active account already has this email. "
                    "Deactivate that account first."
                ),
            ),
        ]

    def clean(self):
        super().clean()
        if not (self.is_active and self.email):
            return
        holder = (
            User.objects.filter(is_active=True, email__iexact=self.email)
            .exclude(pk=self.pk)
            .first()
        )
        if holder:
            raise ValidationError(
                {
                    "email": f"{holder.display_name} ({holder.username}) still has "
                    "this email. Deactivate their account first."
                }
            )

    def save(self, *args, **kwargs):
        # A leaver's mailbox goes to someone else; the old address stays in
        # the account's history only.
        if not self.is_active:
            self.email = ""
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "is_active" in update_fields:
                kwargs["update_fields"] = {*update_fields, "email"}
        super().save(*args, **kwargs)

    @classmethod
    def normalize_username(cls, username):
        username = super().normalize_username(username)
        return username.strip().upper() if isinstance(username, str) else username

    @property
    def display_name(self):
        # Leavers are anonymised wherever people see each other.
        if not self.is_active:
            return "Former employee"
        return self.get_full_name() or self.username

    @property
    def is_office_admin(self):
        """Superusers and the Office admin group: they run the office's setup."""
        return self.is_superuser or self.groups.filter(name="Office admin").exists()
