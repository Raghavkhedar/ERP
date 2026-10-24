from django.core.management.base import BaseCommand

from meetings.services import send_reminders


class Command(BaseCommand):
    help = "Remind both people about meetings starting soon. Run every minute."

    def handle(self, *args, **options):
        sent = send_reminders()
        if sent:
            self.stdout.write(f"Reminded people about {sent} meeting(s).")
