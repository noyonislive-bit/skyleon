from django.core import mail
from django.test import TestCase, override_settings

from apps.accounts.models import User, UserStatus

from .models import EmailMessage, EmailStatus, Notification, NotificationType
from .services import deliver, notify


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_SEND_IMMEDIATELY=False)
class OutboxTests(TestCase):
    def test_notify_creates_notifications_and_outbox_emails(self):
        u = User.objects.create_user("a@example.com", "pw-Strong-1", name="A", status=UserStatus.ACTIVE)
        notify([u], NotificationType.SYSTEM, "Hello", "Body", "/portal/", email_template="announcement",
               context={"announcement": type("A", (), {"title": "Hello", "body": "**Hi**", "project": None})()})
        self.assertEqual(Notification.objects.filter(user=u).count(), 1)
        msg = EmailMessage.objects.get(to="a@example.com")
        self.assertEqual(msg.status, EmailStatus.PENDING)
        self.assertIn("<strong>Hi</strong>", msg.html)
        sent, failed = deliver()
        self.assertEqual((sent, failed), (1, 0))
        self.assertEqual(len(mail.outbox), 1)
        msg.refresh_from_db()
        self.assertEqual(msg.status, EmailStatus.SENT)

    def test_inactive_users_are_skipped(self):
        u = User.objects.create_user("b@example.com", "pw-Strong-1", name="B", status=UserStatus.SUSPENDED)
        notify([u], NotificationType.SYSTEM, "Hello")
        self.assertFalse(Notification.objects.exists())
