"""Settings (company info, notification recipients, system status) and the audit log."""

import platform

import django
from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts.decorators import permission_required_code
from apps.accounts.permissions import has_permission
from apps.comms.models import EmailMessage, EmailStatus
from apps.core import audit, site_settings
from apps.core.models import AuditLog
from apps.training.models import TutorialCategory

from ..forms import CompanySettingsForm, NotificationSettingsForm
from ..helpers import paginate


@permission_required_code("settings.manage")
def settings_view(request):
    company = site_settings.company()
    notif = site_settings.notification_settings()
    company_form = CompanySettingsForm(initial=company, prefix="company")
    notif_form = NotificationSettingsForm(initial={"admin_emails": "\n".join(notif.get("admin_emails") or [])}, prefix="notif")
    if request.method == "POST":
        which = request.POST.get("form")
        if which == "company":
            company_form = CompanySettingsForm(request.POST, prefix="company")
            if company_form.is_valid():
                value = {key: company_form.cleaned_data.get(key, default) for key, default in site_settings.DEFAULT_COMPANY.items()}
                site_settings.set_setting("company", value)
                audit.log(request, "settings.company", None, keys=list(company_form.changed_data))
                messages.success(request, "Company information saved — the website and emails use it immediately.")
                return redirect(reverse("backoffice:settings") + "#company")
            messages.error(request, "Please correct the errors in the company information.")
        elif which == "notifications":
            notif_form = NotificationSettingsForm(request.POST, prefix="notif")
            if notif_form.is_valid():
                site_settings.set_setting("notifications", {"admin_emails": notif_form.cleaned_data["admin_emails"]})
                audit.log(request, "settings.notifications", None, count=len(notif_form.cleaned_data["admin_emails"]))
                messages.success(request, "Notification recipients saved.")
                return redirect(reverse("backoffice:settings") + "#notifications")
            messages.error(request, "Please correct the notification recipients.")
    backend = settings.STORAGE_BACKEND
    system = [
        ("Storage backend", "Object storage (S3-compatible)" if backend == "s3" else "Private server folder (local, signed streaming URLs)"),
        ("Bucket / folder", settings.S3_BUCKET if backend == "s3" else "storage/ (outside public_html)"),
        ("Email backend", _email_backend_label(settings.EMAIL_BACKEND)),
        ("Send email immediately", "Yes (cron retries failures)" if settings.EMAIL_SEND_IMMEDIATELY else "No (cron job delivers)"),
        ("From address", settings.DEFAULT_FROM_EMAIL),
        ("Video completion threshold", f"{settings.VIDEO_COMPLETION_THRESHOLD}% of the video really played"),
        ("Max video upload", f"{settings.MAX_VIDEO_UPLOAD_MB:,} MB"),
        ("Time zone", settings.TIME_ZONE),
        ("Python / Django", f"{platform.python_version()} / {django.get_version()}"),
        ("Debug mode", "On — turn off in production" if settings.DEBUG else "Off"),
    ]
    email_counts = {
        "pending": EmailMessage.objects.filter(status=EmailStatus.PENDING).count(),
        "failed": EmailMessage.objects.filter(status=EmailStatus.FAILED).count(),
    }
    return render(request, "backoffice/system/settings.html", {
        "page_title": "Settings",
        "page_subtitle": "Company information, notification recipients and system status.",
        "crumbs": [("Settings", None)],
        "company_form": company_form,
        "notif_form": notif_form,
        "system": system,
        "email_counts": email_counts,
        "admin_env_emails": list(settings.ADMIN_NOTIFICATION_EMAILS),
        "categories": TutorialCategory.objects.all(),
        "audit": AuditLog.objects.select_related("actor").order_by("-created_at")[:12] if has_permission(request.user, "audit.view") else None,
    })


def _email_backend_label(path):
    name = path.rsplit(".", 2)[-2] if path.count(".") >= 2 else path
    return {
        "smtp": "SMTP (cPanel mail server)",
        "console": "Console — emails are printed to the server log, not sent",
        "locmem": "In-memory (tests)",
        "filebased": "Files on disk",
        "dummy": "Disabled",
    }.get(name, path)


@permission_required_code("audit.view")
def audit_log(request):
    qs = AuditLog.objects.select_related("actor").order_by("-created_at")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(actor__name__icontains=q) | Q(actor__email__icontains=q) | Q(entity_type__icontains=q))
    return render(request, "backoffice/system/audit.html", {
        "page_title": "Audit log",
        "page_subtitle": "Every important administrative action, newest first.",
        "crumbs": [("Settings", reverse("backoffice:settings")), ("Audit log", None)],
        "page": paginate(request, qs, 50),
        "filters": {"q": q},
    })
