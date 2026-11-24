from django.db import migrations


def cancel(apps, schema_editor):
    """Offer calls now come only from a supervisor's Make offer. The ones opened by
    the old rules (selected, HR amount) have no offer behind them; those
    candidates show on the To offer list instead."""
    FollowUp = apps.get_model("hiring", "FollowUp")
    FollowUp.objects.filter(
        purpose="offer", status="pending", person__offers__isnull=True
    ).update(status="cancelled")


class Migration(migrations.Migration):
    dependencies = [("hiring", "0021_backfill_lead_received_on")]
    operations = [migrations.RunPython(cancel, migrations.RunPython.noop)]
