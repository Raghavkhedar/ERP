from django.db import migrations
from django.db.models import Min
from django.utils import timezone


def backfill(apps, schema_editor):
    """Cards sourced here with no lead date get the day they were first sourced.
    Legacy cards have no sourcing row, so they are left as imported."""
    Person = apps.get_model("people", "Person")
    Sourced = apps.get_model("hiring", "SourcedNumber")
    firsts = Sourced.objects.values("person_id").annotate(at=Min("created_at"))
    for row in firsts.iterator():
        Person.objects.filter(pk=row["person_id"], lead_received_on__isnull=True).update(
            lead_received_on=timezone.localtime(row["at"]).date()
        )


class Migration(migrations.Migration):
    dependencies = [
        ("hiring", "0020_calllog_opened_followup"),
        ("people", "0006_backfill_candidate_ids"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
