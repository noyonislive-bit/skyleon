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

    def test_subject_newlines_are_removed(self):
        """A CR/LF typed into a public form must not make the mail library refuse the alert."""
        from .services import queue_email

        msg = queue_email("x@example.com", "Hello\nBcc: evil@example.com", "contact_confirmation",
                          {"msg": type("M", (), {"name": "N"})()})
        self.assertEqual(msg.subject, "Hello Bcc: evil@example.com")
        self.assertEqual(deliver(), (1, 0))

    def test_claimed_message_is_not_sent_twice(self):
        from django.utils import timezone

        from .services import queue_email

        msg = queue_email("y@example.com", "Hi", "contact_confirmation", {"msg": type("M", (), {"name": "N"})()})
        EmailMessage.objects.filter(pk=msg.pk).update(locked_until=timezone.now() + timezone.timedelta(minutes=5))
        self.assertEqual(deliver(), (0, 0))  # another sender holds it
        self.assertEqual(len(mail.outbox), 0)

