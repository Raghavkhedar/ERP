from django.contrib import admin

from core.admin_readonly import ReadOnly
from hiring.admin import CallInline, FollowUpInline, InterviewInline

from .models import Person


@admin.register(Person)
class PersonAdmin(ReadOnly, admin.ModelAdmin):
    """The candidate table. Archived cards show here too; the filter picks them out."""

    list_display = ["id", "name", "phone", "company", "contact_status", "archived_at"]
    list_filter = [
        "company",
        "contact_status",
        ("archived_at", admin.EmptyFieldListFilter),
    ]
    search_fields = [
        "name",
        "phone",
        "phone_key",
        "alternate_phone",
        "phone_3",
        "phone_4",
        "candidate_id",
        "legacy_id",
    ]
    inlines = [FollowUpInline, CallInline, InterviewInline]
