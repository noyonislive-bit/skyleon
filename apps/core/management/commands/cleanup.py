from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comms.models import EmailMessage, EmailStatus, Notification
from apps.storage.models import MediaAsset, MediaStatus
from apps.storage.services import delete_asset


class Command(BaseCommand):
    help = "Daily housekeeping (schedule once a day with cPanel cron)."

    def handle(self, *args, **opts):
        now = timezone.now()
        call_command("clearsessions")
        stale = MediaAsset.objects.filter(status__in=[MediaStatus.UPLOADING, MediaStatus.FAILED], created_at__lt=now - timedelta(days=1))
        n_assets = 0
        for asset in stale:
            delete_asset(asset)
            n_assets += 1
        n_mail = EmailMessage.objects.filter(status=EmailStatus.SENT, created_at__lt=now - timedelta(days=90)).delete()[0]
        n_notif = Notification.objects.filter(read_at__isnull=False, created_at__lt=now - timedelta(days=180)).delete()[0]
        self.stdout.write(f"removed: {n_assets} unfinished uploads, {n_mail} old emails, {n_notif} old notifications")
