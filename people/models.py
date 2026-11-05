import re

from django.db import models
from simple_history.models import HistoricalRecords


def phone_key(phone):
    """The last 10 digits: how the same person is recognised across spellings
    (+91, 0 prefix, spaces)."""
    return re.sub(r"\D", "", phone)[-10:]


class Person(models.Model):
    """One card per person. It stays with them through hiring, onboarding and
    offboarding; last call, stage and the like are worked out when shown, never
    stored here."""

    class ContactStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed (time lapse)"
        DO_NOT_CALL = "do_not_call", "Do not call"
        ON_DEMAND = "on_demand", "On-demand base"
        HOLD_FF = "hold_ff", "Hold - FF"

    class Priority(models.TextChoices):
        PREFERRED = "preferred", "Preferred"
        SEMI = "semi", "Semi-preferred"
        LEAST = "least", "Least-preferred"

    company = models.ForeignKey(
        "core.Company", on_delete=models.PROTECT, related_name="people"
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30)
    phone_key = models.CharField(max_length=10, db_index=True, editable=False)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    current_employer = models.CharField(max_length=200, blank=True)
    current_salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    expected_salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    experience_years = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    joining_period = models.CharField(max_length=60, blank=True)
    contact_status = models.CharField(
        max_length=20, choices=ContactStatus, default=ContactStatus.ACTIVE
    )
    priority = models.CharField(max_length=20, choices=Priority, blank=True)
    zoho_id = models.CharField(max_length=40, blank=True)
    # Bumped on every save; a form that carries an older number was opened
    # before someone else saved, and is rejected.
    version = models.PositiveIntegerField(default=1)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name_plural = "people"
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["zoho_id"],
                condition=~models.Q(zoho_id=""),
                name="people_person_unique_zoho_id",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.phone_key = phone_key(self.phone)
        super().save(*args, **kwargs)

    def same_number(self):
        """Other cards sharing this phone number. Never merged, only linked."""
        if not self.phone_key:
            return Person.objects.none()
        return Person.objects.filter(phone_key=self.phone_key).exclude(pk=self.pk)
