from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from meetings.services import open_office_hours


class Command(BaseCommand):
    help = "Open everyone's office hours for the coming days. Safe to run again."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7, help="How far ahead.")

    def handle(self, *args, days, **options):
        today = timezone.localdate()
        people = get_user_model().objects.filter(is_active=True).order_by("pk")
        opened = 0
        for person in people:
            for ahead in range(days):
                opened += len(open_office_hours(person, today + timedelta(ahead)))
        self.stdout.write(f"Opened {opened} office-hours slots.")
