from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User

PRIVILEGE_FIELDS = {"is_staff", "is_superuser", "groups", "user_permissions"}


@admin.register(User)
class OfficeUserAdmin(UserAdmin):
    """Superusers see everything. Office admins manage ordinary accounts only."""

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            return fieldsets
        return [
            (
                name,
                {
                    **options,
                    "fields": [
                        f for f in options["fields"] if f not in PRIVILEGE_FIELDS
                    ],
                },
            )
            for name, options in fieldsets
        ]

    def get_queryset(self, request):
        users = super().get_queryset(request)
        if request.user.is_superuser:
            return users
        return users.filter(is_superuser=False, is_staff=False)
