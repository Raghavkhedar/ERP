from django.contrib.auth.management import create_permissions
from django.db import migrations

GROUP_NAME = "Office admin"

PERMISSIONS = [
    ("core", "add_user"),
    ("core", "change_user"),
    ("core", "view_user"),
    ("chat", "add_conversation"),
    ("chat", "change_conversation"),
    ("chat", "view_conversation"),
    ("chat", "add_membership"),
    ("chat", "change_membership"),
    ("chat", "delete_membership"),
    ("chat", "view_membership"),
]


def create_group(apps, schema_editor):
    # Permissions are normally created after all migrations finish, so on a
    # fresh database they don't exist yet here. Create them first.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    for app_label, codename in PERMISSIONS:
        group.permissions.add(
            Permission.objects.get(
                content_type__app_label=app_label, codename=codename
            )
        )


def delete_group(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("core", "0002_historicaluser"),
        ("chat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_group, delete_group),
    ]
