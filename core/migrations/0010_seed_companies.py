from django.db import migrations

SHARED_EMPLOYEE_ID = "S381"  # Anushman: works for both, paid by Avris


def seed(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    Membership = apps.get_model("core", "Membership")
    User = apps.get_model("core", "User")

    senken, _ = Company.objects.get_or_create(slug="senken", defaults={"name": "Senken"})
    avris, _ = Company.objects.get_or_create(slug="avris", defaults={"name": "Avris"})

    # Everyone so far has worked for Senken, and Senken pays them.
    for user in User.objects.filter(is_active=True):
        Membership.objects.get_or_create(
            user=user, company=senken, defaults={"pays_salary": True}
        )

    shared = User.objects.filter(username=SHARED_EMPLOYEE_ID).first()
    if shared:
        Membership.objects.filter(user=shared, company=senken).update(pays_salary=False)
        Membership.objects.update_or_create(
            user=shared, company=avris, defaults={"pays_salary": True}
        )


def unseed(apps, schema_editor):
    apps.get_model("core", "Membership").objects.all().delete()
    apps.get_model("core", "Company").objects.filter(slug__in=["senken", "avris"]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0009_companies_access")]

    operations = [migrations.RunPython(seed, unseed)]
