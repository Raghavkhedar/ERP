import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from hiring import legacy_import


class Command(BaseCommand):
    help = (
        "Import the old system's export. Without --apply nothing is saved: it "
        "shows what would happen."
    )

    def add_arguments(self, parser):
        parser.add_argument("archive", help="the export .zip")
        parser.add_argument("--apply", action="store_true", help="save for real")
        parser.add_argument(
            "--review",
            default="import-review.csv",
            help="where to write the review list",
        )

    def handle(self, archive, apply, review, **options):
        if not Path(archive).is_file():
            raise CommandError(f"No such file: {archive}")
        stats, rows = legacy_import.from_archive(
            archive, apply=apply, log=self.stdout.write
        )
        extras = {k: stats.pop(k) for k in list(stats) if k.startswith("_")}
        for key, n in stats.items():
            self.stdout.write(f"{key}: {n}")
        self.stdout.write("\nNames found among existing users:")
        for old, now in sorted(extras["_matched"].items()):
            self.stdout.write(f"  {old} -> {now}")
        self.stdout.write("Names with no account (made inactive):")
        for name in extras["_created"]:
            self.stdout.write(f"  {name}")
        self.stdout.write("\nMost common notes left out (shifts and parking):")
        for note, n in extras["_shift_notes"]:
            self.stdout.write(f"  {n:6}  {note}")
        self.stdout.write("Most common notes kept as calls:")
        for note, n in extras["_other_notes"]:
            self.stdout.write(f"  {n:6}  {note}")
        with open(review, "w", newline="") as f:
            csv.writer(f).writerows([("what", "candidate / value", "detail"), *rows])
        self.stdout.write(f"\n{len(rows)} things to look at in {review}")
        self.stdout.write(
            "SAVED." if apply else "Dry run: nothing was saved. Add --apply to save."
        )
