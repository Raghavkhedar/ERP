from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Slot


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
