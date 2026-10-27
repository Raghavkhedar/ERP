from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Attachment, Note, RedFlag
from .services import can_read


@admin.register(RedFlag)
class RedFlagAdmin(SimpleHistoryAdmin):
    """Superadmins only: staff with model permissions still see nothing."""

    list_display = ["__str__", "incident_date", "status", "created_at"]
    list_filter = ["status", "created_at"]
    raw_id_fields = ["raised_by", "raised_against"]

    def has_module_permission(self, request):
        return can_read(request.user)

    def has_view_permission(self, request, obj=None):
        return can_read(request.user)

    def has_change_permission(self, request, obj=None):
        return can_read(request.user)

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class SuperadminOnly:
    """Notes and evidence stay private: only superadmins see or change them."""

    def has_module_permission(self, request):
        return can_read(request.user)

    def has_view_permission(self, request, obj=None):
        return can_read(request.user)

    def has_change_permission(self, request, obj=None):
        return can_read(request.user)

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Note)
class NoteAdmin(SuperadminOnly, admin.ModelAdmin):
    list_display = ["red_flag", "author", "body"]
    raw_id_fields = ["red_flag", "author"]


@admin.register(Attachment)
class RedFlagAttachmentAdmin(SuperadminOnly, admin.ModelAdmin):
    list_display = ["original_name", "red_flag", "size"]
    raw_id_fields = ["red_flag"]
