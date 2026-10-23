from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Task


@admin.register(Task)
class TaskAdmin(SimpleHistoryAdmin):
    list_display = ["__str__", "assigned_to", "status", "due_date", "received_at"]
    list_filter = ["status", "received_at"]
    search_fields = ["description", "assigned_to__username", "assigned_to__first_name"]
    date_hierarchy = "received_at"
    raw_id_fields = ["assigned_to", "assigned_by"]
