from django.core.management.base import BaseCommand
from django.db.models import Q

from people.models import Person


class Command(BaseCommand):
    help = (
        "Unarchive archived cards that have follow-ups, calls, interviews or offers: "
        "archived cards are hidden from Candidates, so that work could not be found. "
        "Without --apply nothing is saved."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="save for real")

    def handle(self, apply, **options):
        cards = list(
            Person.objects.filter(archived_at__isnull=False)
            .filter(
                Q(followups__isnull=False)
                | Q(calls__isnull=False)
                | Q(interviews__isnull=False)
                | Q(offers__isnull=False)
            )
            .distinct()
        )
        for p in cards:
            self.stdout.write(f"{p.pk} {p.name} {p.phone}")
            if apply:
                p.archived_at = None
                p.version += 1
                p.save(update_fields=["archived_at", "version"])
        verb = "unarchived" if apply else "would be unarchived (use --apply)"
        self.stdout.write(f"{len(cards)} card(s) {verb}")
