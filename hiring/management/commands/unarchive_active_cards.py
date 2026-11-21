from django.core.management.base import BaseCommand
from django.db.models import Q

from people.models import Person
from people.services import unarchive


class Command(BaseCommand):
    help = (
        "Unarchive archived cards that have follow-ups, calls, interviews or offers: "
        "archived cards were hidden from Candidates, so that work could not be found. "
        "A number that already has a live card is skipped. Without --apply nothing "
        "is saved."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="save for real")

    def handle(self, apply, **options):
        cards = (
            Person.objects.filter(archived_at__isnull=False)
            .filter(
                Q(followups__isnull=False)
                | Q(calls__isnull=False)
                | Q(interviews__isnull=False)
                | Q(offers__isnull=False)
            )
            .distinct()
            .order_by("pk")
        )
        # (company, number) pairs that have a live card, or get one from this run.
        taken = set(
            Person.objects.filter(archived_at__isnull=True).values_list(
                "company_id", "phone_key"
            )
        )
        done = skipped = 0
        for p in cards:
            if (p.company_id, p.phone_key) in taken:
                skipped += 1
                self.stdout.write(
                    f"skip {p.pk} {p.name} {p.phone}: number has a live card"
                )
                continue
            taken.add((p.company_id, p.phone_key))
            done += 1
            self.stdout.write(f"{p.pk} {p.name} {p.phone}")
            if apply:
                unarchive(p)
        verb = "unarchived" if apply else "would be unarchived (use --apply)"
        self.stdout.write(f"{done} card(s) {verb}, {skipped} skipped")
