import re

from django.db import migrations


def backfill(apps, schema_editor):
    Person = apps.get_model("people", "Person")
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
    # shortcut: skips the per-card history rows, fine for a one-off backfill.
    Person.objects.bulk_update(empty, ["candidate_id"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("people", "0005_more_phone_numbers")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
