"""
Notifications and email.

    notify(users, NotificationType.FEEDBACK, "New feedback #004", link="/portal/feedback/4/",
           email_template="new_feedback", context={...})

    send_email("someone@example.com", "Subject", "template_name", {...})

Emails are written to the EmailMessage outbox first. With EMAIL_SEND_IMMEDIATELY
they are delivered at the end of the request; anything that fails is retried by
`python manage.py process_emails` (run from a cPanel cron job).
"""

import logging
from collections.abc import Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core import site_settings

from .models import EmailMessage, EmailStatus, Notification

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def absolute_url(path: str) -> str:
    if not path:
        return settings.APP_URL
    if path.startswith("http"):
        return path
    return f"{settings.APP_URL}{path}"


def render_email(template: str, context: dict) -> tuple[str, str]:
    ctx = {
        "brand": site_settings.BRAND,
        "company": site_settings.company(),
        "APP_URL": settings.APP_URL,
        "TIME_ZONE": settings.TIME_ZONE,
        **context,
    }
    html = render_to_string(f"emails/{template}.html", ctx)
    text = render_to_string(f"emails/{template}.txt", ctx)
    return html, text


def queue_email(to: str, subject: str, template: str, context: dict | None = None) -> EmailMessage | None:
    if not to:
        return None
    html, text = render_email(template, {"subject": subject, **(context or {})})
    msg = EmailMessage.objects.create(to=to, subject=subject[:300], html=html, text=text, template=template)
    if settings.EMAIL_SEND_IMMEDIATELY:
        transaction.on_commit(lambda: deliver([msg.pk]))
    return msg


def send_email(to, subject: str, template: str, context: dict | None = None):
    recipients = [to] if isinstance(to, str) else list(to)
    return [queue_email(r, subject, template, context) for r in recipients if r]


def notify_admins(subject: str, template: str, context: dict | None = None):
    return send_email(site_settings.admin_notification_emails(), subject, template, context)


def deliver(ids: Iterable[int] | None = None, limit: int = 50) -> tuple[int, int]:
    """Deliver pending emails. Returns (sent, failed)."""
    qs = EmailMessage.objects.filter(status=EmailStatus.PENDING, attempts__lt=MAX_ATTEMPTS)
    if ids is not None:
        qs = qs.filter(pk__in=list(ids))
    batch = list(qs.order_by("created_at")[:limit])
    if not batch:
        return 0, 0
    sent = failed = 0
    try:
        connection = get_connection(fail_silently=False)
        connection.open()
    except Exception as exc:  # SMTP down — leave everything pending for the cron retry
        logger.warning("Email connection failed: %s", exc)
        EmailMessage.objects.filter(pk__in=[m.pk for m in batch]).update(last_error=str(exc)[:1000])
        return 0, len(batch)
    try:
        for msg in batch:
            msg.attempts += 1
            try:
                email = EmailMultiAlternatives(
                    subject=msg.subject, body=msg.text, from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[msg.to], connection=connection,
                )
                email.attach_alternative(msg.html, "text/html")
                email.send()
                msg.status = EmailStatus.SENT
                msg.sent_at = timezone.now()
                msg.last_error = ""
                sent += 1
            except Exception as exc:
                logger.warning("Email to %s failed: %s", msg.to, exc)
                msg.last_error = str(exc)[:1000]
                if msg.attempts >= MAX_ATTEMPTS:
                    msg.status = EmailStatus.FAILED
                failed += 1
            msg.save(update_fields=["status", "attempts", "sent_at", "last_error"])
    finally:
        try:
            connection.close()
        except Exception:
            pass
    return sent, failed


def notify(
    users,
    ntype: str,
    title: str,
    body: str = "",
    link: str = "",
    *,
    email_template: str | None = None,
    email_subject: str | None = None,
    context: dict | None = None,
):
    """Create in-app notifications (and optionally emails) for one or many users."""
    if hasattr(users, "pk"):
        users = [users]
    users = [u for u in users if u is not None and u.is_active]
    if not users:
        return
    Notification.objects.bulk_create(
        [Notification(user=u, ntype=ntype, title=title[:200], body=body[:500], link=link) for u in users]
    )
    if email_template:
        for u in users:
            queue_email(
                u.email,
                email_subject or title,
                email_template,
                {"user": u, "title": title, "body": body, "link": absolute_url(link), **(context or {})},
            )
