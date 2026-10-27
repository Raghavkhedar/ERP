from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Conference, Invitation, Slot


@admin.register(Slot)
class SlotAdmin(SimpleHistoryAdmin):
    list_display = [
        "host",
        "starts_at",
        "ends_at",
        "booked_by",
        "topic",
        "cancelled_at",
    ]
    list_filter = ["starts_at"]
    search_fields = ["host__username", "booked_by__username", "topic"]
    date_hierarchy = "starts_at"
    raw_id_fields = ["host", "booked_by"]


class InvitationInline(admin.TabularInline):
    model = Invitation
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Conference)
class ConferenceAdmin(admin.ModelAdmin):
    list_display = ["title", "host", "starts_at"]
    search_fields = ["title", "host__username"]
    raw_id_fields = ["host"]
    inlines = [InvitationInline]
