from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comms.models import EmailMessage, EmailStatus, Notification
from apps.storage.models import MediaAsset, MediaStatus
from apps.storage.services import delete_asset

CLOSED_LEADS = ("lost", "archived")


class Command(BaseCommand):
    help = "Daily housekeeping (schedule once a day with cPanel cron)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--purge-days", type=int, default=0,
            help="Also delete personal data no longer needed: rejected job applications and lost/archived quote "
                 "requests and contact messages older than this many days, with their uploaded files (0 = off).",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        call_command("clearsessions")
        stale = MediaAsset.objects.filter(status__in=[MediaStatus.UPLOADING, MediaStatus.FAILED], created_at__lt=now - timedelta(days=1))
        n_assets = 0
        for asset in stale:
            delete_asset(asset)
            n_assets += 1
        # Delivered emails after 90 days; failed ones (they contain personal data too) after 180.
        n_mail = EmailMessage.objects.filter(status=EmailStatus.SENT, created_at__lt=now - timedelta(days=90)).delete()[0]
        n_mail += EmailMessage.objects.filter(status=EmailStatus.FAILED, created_at__lt=now - timedelta(days=180)).delete()[0]
        n_notif = Notification.objects.filter(read_at__isnull=False, created_at__lt=now - timedelta(days=180)).delete()[0]
        self.stdout.write(f"removed: {n_assets} unfinished uploads, {n_mail} old emails, {n_notif} old notifications")
        if opts["purge_days"] > 0:
            self.stdout.write(self._purge(now - timedelta(days=opts["purge_days"])))

    def _purge(self, cutoff):
        from apps.website.models import ApplicationStatus, ContactMessage, JobApplication, QuoteRequest

        files = 0
        apps = JobApplication.objects.filter(status=ApplicationStatus.REJECTED, created_at__lt=cutoff)
        quotes = QuoteRequest.objects.filter(status__in=CLOSED_LEADS, created_at__lt=cutoff)
        for obj in list(apps) + list(quotes):
            for asset in (getattr(obj, "cv", None), getattr(obj, "sample", None), getattr(obj, "attachment", None)):
                if asset is not None:
                    delete_asset(asset)
                    files += 1
        n_apps = apps.delete()[0]
        n_quotes = quotes.delete()[0]
        n_msgs = ContactMessage.objects.filter(status__in=CLOSED_LEADS, created_at__lt=cutoff).delete()[0]
        return f"purged: {n_apps} rejected applications, {n_quotes} closed quote requests, {n_msgs} closed messages, {files} files"
