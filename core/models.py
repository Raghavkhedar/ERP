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

    must_change_password = models.BooleanField(
        default=True,
        help_text="Set for new accounts and after an admin resets the password: "
        "the person must choose their own before using the app.",
    )

    supervisor = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports",
        help_text="Who red flags and feedback about this person can be handed to.",
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
            models.CheckConstraint(
                condition=~Q(supervisor=models.F("pk")),
                name="core_user_not_own_supervisor",
                violation_error_message="Nobody can be their own supervisor.",
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

    @property
    def is_trainer(self):
        """Members of the Trainer group: they read feedback and write lessons."""
        return self.groups.filter(name="Trainer").exists()


class Company(models.Model):
    """A legal entity the office keeps separate books for."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    """A person's place in a company. Someone can belong to several."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="memberships"
    )
    designation = models.CharField(max_length=100, blank=True)
    joined_on = models.DateField(null=True, blank=True)
    pays_salary = models.BooleanField(
        default=False,
        help_text="This company pays the person's salary. Only one per person.",
    )

    class Meta:
        ordering = ["company__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "company"], name="core_membership_one_per_company"
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(pays_salary=True),
                name="core_membership_one_paying_company",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} at {self.company}"


class AccessGrant(models.Model):
    """Lets a person into one section of a module for one company.

    The sections and modules are listed in core.access; a section nobody has
    been granted stays out of their navigation and answers 403.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="access_grants"
    )
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="access_grants"
    )
    module = models.CharField(max_length=30)
    section = models.CharField(max_length=30)
    granted_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "company", "module", "section"],
                name="core_accessgrant_unique",
            ),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.module}/{self.section} at {self.company}"
