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
import threading
from collections.abc import Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone, translation

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


# Emails employees receive are written in Bangla (like the portal); dates/numbers in them are formatted to match.
BANGLA_EMAILS = frozenset({
    "account_approved", "account_invite", "announcement", "meeting_invite", "new_feedback",
    "new_test", "new_training", "password_reset", "project_assigned",
})


def render_email(template: str, context: dict) -> tuple[str, str]:
    with translation.override("bn" if template in BANGLA_EMAILS else "en"):
        return _render_email(template, context)


def _render_email(template: str, context: dict) -> tuple[str, str]:
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


# Emails sent during a web request are delivered after the transaction commits, all over one
# SMTP connection; at most this many — the rest (e.g. a big announcement) go out with the cron job,
# so a slow or unreachable mail server can't hold a page for long.
IMMEDIATE_SEND_MAX = 10
LOCK_SECONDS = 300
_pending = threading.local()


def clean_subject(subject: str) -> str:
    """Single line (a CR/LF from user input would make the mail library refuse the message)."""
    return " ".join(str(subject or "").split())[:300]


def queue_email(to: str, subject: str, template: str, context: dict | None = None, *, reply_to: str = "") -> EmailMessage | None:
    if not to:
        return None
    subject = clean_subject(subject)
    html, text = render_email(template, {"subject": subject, **(context or {})})
    msg = EmailMessage.objects.create(to=to, subject=subject, html=html, text=text, template=template,
                                      reply_to=reply_to if reply_to and "\n" not in reply_to else "")
    if settings.EMAIL_SEND_IMMEDIATELY:
        _schedule_delivery(msg.pk)
    return msg


def _schedule_delivery(pk: int) -> None:
    ids = getattr(_pending, "ids", None)
    if ids is not None:  # inside a web request: EmailDeliveryMiddleware sends them all at the end
        ids.append(pk)
        return
    transaction.on_commit(lambda: deliver([pk]))  # management commands / shell


class EmailDeliveryMiddleware:
    """Collects the emails queued while handling a request and delivers them once the view has
    finished (and its transaction committed): one SMTP connection, at most IMMEDIATE_SEND_MAX
    messages; anything else stays in the outbox for `process_emails`."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _pending.ids = []
        try:
            response = self.get_response(request)
        finally:
            ids, _pending.ids = _pending.ids, None
        if ids:
            try:
                deliver(ids[:IMMEDIATE_SEND_MAX])
            except Exception:  # never turn a sent page into an error because of email
                logger.exception("Immediate email delivery failed; the cron job will retry")
        return response


def send_email(to, subject: str, template: str, context: dict | None = None, *, reply_to: str = ""):
    recipients = [to] if isinstance(to, str) else list(to)
    return [queue_email(r, subject, template, context, reply_to=reply_to) for r in recipients if r]


def notify_admins(subject: str, template: str, context: dict | None = None, *, reply_to: str = ""):
    return send_email(site_settings.admin_notification_emails(), subject, template, context, reply_to=reply_to)


def _claim(ids) -> list[int]:
    """Lock each pending message for this sender (atomic per row); returns the ids we own."""
    now = timezone.now()
    owned = []
    for pk in ids:
        got = EmailMessage.objects.filter(pk=pk, status=EmailStatus.PENDING).filter(
            Q(locked_until__isnull=True) | Q(locked_until__lt=now)
        ).update(locked_until=now + timezone.timedelta(seconds=LOCK_SECONDS))
        if got:
            owned.append(pk)
    return owned


def deliver(ids: Iterable[int] | None = None, limit: int = 50) -> tuple[int, int]:
    """Deliver pending emails (all of them, or the given ids). Returns (sent, failed)."""
    qs = EmailMessage.objects.filter(status=EmailStatus.PENDING, attempts__lt=MAX_ATTEMPTS)
    if ids is not None:
        qs = qs.filter(pk__in=list(ids))
    candidates = list(qs.order_by("created_at").values_list("pk", flat=True)[:limit])
    owned = _claim(candidates)
    batch = list(EmailMessage.objects.filter(pk__in=owned).order_by("created_at"))
    if not batch:
        return 0, 0
    sent = failed = 0
    try:
        connection = get_connection(fail_silently=False)
        connection.open()
    except Exception as exc:  # SMTP down — count the attempt, keep the messages for the cron retry
        logger.warning("Email connection failed: %s", exc)
        for msg in batch:
            msg.attempts += 1
            msg.last_error = str(exc)[:1000]
            msg.locked_until = None
            if msg.attempts >= MAX_ATTEMPTS:
                msg.status = EmailStatus.FAILED
            msg.save(update_fields=["attempts", "last_error", "locked_until", "status"])
        return 0, len(batch)
    try:
        for msg in batch:
            msg.attempts += 1
            try:
                email = EmailMultiAlternatives(
                    subject=clean_subject(msg.subject), body=msg.text, from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[msg.to], reply_to=[msg.reply_to] if msg.reply_to else None, connection=connection,
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
            msg.locked_until = None
            msg.save(update_fields=["status", "attempts", "sent_at", "last_error", "locked_until"])
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
