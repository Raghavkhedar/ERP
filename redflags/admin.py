from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import RedFlag
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
        return False

    def has_delete_permission(self, request, obj=None):
        return False
