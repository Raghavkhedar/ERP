from django.db import migrations

GROUP_NAME = "Trainer"


def create_group(apps, schema_editor):
    # No permissions: being a trainer is a label the feedback pages look for.
    apps.get_model("auth", "Group").objects.get_or_create(name=GROUP_NAME)


def delete_group(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("core", "0006_must_change_password"),
    ]

    operations = [
        migrations.RunPython(create_group, delete_group),
    ]
