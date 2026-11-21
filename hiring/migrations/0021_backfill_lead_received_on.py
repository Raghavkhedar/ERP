from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    """Cards sourced here with no lead date get the day they were first sourced.
    Legacy cards have no sourcing row, so they are left as imported."""
    Person = apps.get_model("people", "Person")
    Sourced = apps.get_model("hiring", "SourcedNumber")
    first = {}
    for person_id, at in Sourced.objects.order_by("-created_at").values_list(
        "person_id", "created_at"
    ):
        first[person_id] = timezone.localtime(at).date()  # ends on the oldest
    for person_id, day in first.items():
        Person.objects.filter(pk=person_id, lead_received_on__isnull=True).update(
            lead_received_on=day
        )


class Migration(migrations.Migration):
    dependencies = [
        ("hiring", "0020_calllog_opened_followup"),
        ("people", "0006_backfill_candidate_ids"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
