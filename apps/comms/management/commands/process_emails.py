from django.core.management.base import BaseCommand

from apps.comms.services import deliver


class Command(BaseCommand):
    help = "Deliver pending emails from the outbox. Schedule every 5 minutes with a cPanel cron job."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **opts):
        sent, failed = deliver(limit=opts["limit"])
        self.stdout.write(f"sent={sent} failed={failed}")
