import re

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Person = apps.get_model("people", "Person")
    History = apps.get_model("people", "HistoricalPerson")
    with schema_editor.connection.cursor() as cursor:
        # The same lock hiring.services.lock_candidate_ids takes, so a recruiter
        # sourcing a number during the deploy can't take one of ours.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('candidate_id'))")
    used = [
        int(m.group(1))
        for cid in Person.objects.filter(candidate_id__startswith="WJ").values_list(
            "candidate_id", flat=True
        )
        if (m := re.fullmatch(r"WJ(\d+)", cid))
    ]
    n = max(used, default=0)
    empty = list(Person.objects.filter(candidate_id="").order_by("id"))
    for person in empty:
        n += 1
        person.candidate_id = f"WJ{n}"
    Person.objects.bulk_update(empty, ["candidate_id"], batch_size=500)
    # bulk_update skips simple_history, so write each change's history row here.
    now = timezone.now()
    History.objects.bulk_create(
        [
            History(
                **{f.attname: getattr(p, f.attname) for f in Person._meta.concrete_fields},
                history_date=now,
                history_type="~",
                history_change_reason="Candidate ID backfill",
            )
            for p in empty
        ],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [("people", "0005_more_phone_numbers")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
