from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Attachment, DateChange, Task, TaskUpdate


@admin.register(Task)
class TaskAdmin(SimpleHistoryAdmin):
    list_display = ["__str__", "assigned_to", "status", "due_date", "received_at"]
    list_filter = ["status", "received_at"]
    search_fields = ["description", "assigned_to__username", "assigned_to__first_name"]
    date_hierarchy = "received_at"
    raw_id_fields = ["assigned_to", "assigned_by"]


@admin.register(TaskUpdate)
class TaskUpdateAdmin(admin.ModelAdmin):
    list_display = ["task", "author", "created_at", "summary"]
    search_fields = ["body", "author__username", "author__first_name"]
    date_hierarchy = "created_at"
    raw_id_fields = ["task", "author"]


@admin.register(Attachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ["original_name", "task", "update", "size"]
    search_fields = ["original_name"]
    raw_id_fields = ["task", "update"]


@admin.register(DateChange)
class DateChangeAdmin(admin.ModelAdmin):
    list_display = ["task", "changed_by", "old_date", "new_date", "created_at"]
    search_fields = ["reason", "changed_by__username", "changed_by__first_name"]
    raw_id_fields = ["task", "changed_by"]
