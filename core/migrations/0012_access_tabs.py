from django.db import migrations

# Today's "candidates" section gates every one of these pages, so it becomes all of them.
CANDIDATES = [
    "people",
    "sourcing",
    "screening",
    "calling",
    "selecting",
    "hiring",
    "onboarding",
]


def convert(apps, schema_editor):
    """Split the old Empanelment sections into tabs without changing who can open what."""
    Grant = apps.get_model("core", "AccessGrant")
    Log = apps.get_model("core", "AccessLog")
    old = list(
        Grant.objects.filter(
            module="recruitment", section__in=["candidates", "interviews"]
        ).select_related("user", "company")
    )
    for grant in old:
        # interviews had no page; it only ever meant "may sit in Selecting".
        tabs = CANDIDATES if grant.section == "candidates" else ["selecting"]
        for tab in tabs:
            _, made = Grant.objects.get_or_create(
                user=grant.user,
                company=grant.company,
                module="recruitment",
                section=tab,
                defaults={"granted_by": grant.granted_by},
            )
            if made:
                Log.objects.create(
                    subject=grant.user,
                    subject_name=grant.user.first_name or grant.user.username,
                    company=grant.company,
                    module="recruitment",
                    section=tab,
                    action="grant",
                    actor_name="migrated",
                    note="migrated",
                )
    Grant.objects.filter(
        module="recruitment", section__in=["candidates", "interviews"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0011_access_manager_log")]

    operations = [
        # Going back would have to guess which tabs were one old section.
        migrations.RunPython(convert, migrations.RunPython.noop),
    ]
