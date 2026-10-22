import re

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import RegexValidator
from django.db import models
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

    @classmethod
    def normalize_username(cls, username):
        username = super().normalize_username(username)
        return username.strip().upper() if isinstance(username, str) else username

    @property
    def display_name(self):
        return self.get_full_name() or self.username
