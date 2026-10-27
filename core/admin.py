from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm

from .models import User

PRIVILEGE_FIELDS = {"is_staff", "is_superuser", "groups", "user_permissions"}


class AddUserForm(AdminUserCreationForm):
    """New accounts need a name: it is what everyone sees in chat and meetings."""

    class Meta(AdminUserCreationForm.Meta):
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True


@admin.register(User)
class OfficeUserAdmin(UserAdmin):
    """Superusers see everything. Office admins manage ordinary accounts only."""

    add_form = AddUserForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "first_name",
                    "last_name",
                    "email",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    fieldsets = tuple(
        (
            name,
            {**options, "fields": (*options["fields"], "supervisor")}
            if name == "Personal info"
            else options,
        )
        for name, options in UserAdmin.fieldsets
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "supervisor":
            kwargs["queryset"] = User.objects.filter(is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

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

    def user_change_password(self, request, id, form_url=""):
        # A password an admin sets is known to the admin: make the person
        # choose their own at next login.
        before = User.objects.filter(pk=id).values_list("password", flat=True).first()
        response = super().user_change_password(request, id, form_url)
        after = User.objects.filter(pk=id).values_list("password", flat=True).first()
        if before is not None and after != before:
            User.objects.filter(pk=id).update(must_change_password=True)
        return response
