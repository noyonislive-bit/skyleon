"""
Admin-panel template helpers.

  {% admin_nav as nav %}                     sidebar items, permission flags, badge counts (cached per request)
  {% asset_url asset %}                       signed URL for a MediaAsset (staff pages only — scope already checked)
  {% uploader form.video kind="video" purpose="tutorial" %}   direct-to-storage upload widget
  {{ value|bar_width:max }}                   0–100 width for CSS bars
"""

import uuid

from django import template
from django.urls import NoReverseMatch, reverse

from apps.accounts.models import Role, User, UserStatus
from apps.accounts.permissions import has_permission
from apps.storage.models import MediaAsset
from apps.storage.services import media_url

register = template.Library()

# key, label, url name, icon, permission, badge key, extra active prefixes
NAV = [
    ("Overview", [
        ("dashboard", "Dashboard", "backoffice:dashboard", "layout-dashboard", "backoffice.access", None, ()),
    ]),
    ("People", [
        ("employees", "Employees", "backoffice:employee_list", "users", "employees.view", "pending", ()),
        ("applicants", "Applicants", "backoffice:applicant_list", "briefcase", "applicants.manage", "applicants", ()),
    ]),
    ("Business", [
        ("clients", "Clients", "backoffice:organization_list", "building-2", "clients.manage", None, ("/admin/client-accounts/",)),
        ("leads", "Quote requests", "backoffice:lead_list", "file-text", "leads.manage", "leads", ()),
        ("messages", "Messages", "backoffice:message_list", "message-square", "leads.manage", "messages", ()),
    ]),
    ("Projects", [
        ("projects", "Projects", "backoffice:project_list", "folder-open", "backoffice.access", None,
         ("/admin/guidelines/", "/admin/onboarding/", "/admin/teams/")),
    ]),
    ("Training", [
        ("tutorials", "Tutorials", "backoffice:tutorial_list", "circle-play", "content.manage", None, ()),
        ("training", "Training progress", "backoffice:training_progress", "graduation-cap", "reports.view", None, ()),
        ("company_onboarding", "Company onboarding", "backoffice:company_onboarding", "route", "content.manage", None, ("/admin/company-onboarding/",)),
        ("practice", "Practice lab", "practice:manage", "clapperboard", "content.manage", None, ()),
        ("guides", "Work guides", "guides:manage", "book-open-check", "content.manage", None, ("/admin/guides/",)),
    ]),
    ("Quality", [
        ("feedback", "Feedback", "backoffice:feedback_list", "message-square-text", "content.manage", None, ()),
        ("tracking", "Feedback tracking", "backoffice:feedback_tracking", "scan-eye", "content.manage", None, ()),
        ("tests", "Tests", "backoffice:test_list", "clipboard-check", "content.manage", None, ("/admin/questions/", "/admin/attempts/")),
    ]),
    ("Communication", [
        ("announcements", "Announcements", "backoffice:announcement_list", "megaphone", "announcements.manage", None, ()),
        ("meetings", "Meetings", "backoffice:meeting_list", "calendar-clock", "meetings.manage", None, ()),
        ("emails", "Email log", "backoffice:email_list", "mail", "emails.view", "emails_failed", ()),
    ]),
    ("Insights", [
        ("reports", "Reports", "backoffice:reports", "bar-chart-3", "reports.view", None, ()),
    ]),
    ("System", [
        ("settings", "Settings", "backoffice:settings", "settings", "settings.manage", None, ("/admin/audit/",)),
    ]),
]

FLAG_CODES = [
    "employees.view", "employees.manage", "staff.manage", "applicants.manage", "leads.manage", "clients.manage", "projects.create",
    "projects.manage", "content.manage", "announcements.manage", "meetings.manage", "reports.view", "emails.view",
    "settings.manage", "audit.view", "portal.access",
]


def _counts(request, flags):
    from apps.comms.models import EmailMessage, EmailStatus
    from apps.website.models import ApplicationStatus, ContactMessage, JobApplication, LeadStatus, QuoteRequest

    from ..helpers import employee_scope

    user = request.user
    counts = {}
    if flags["employees_view"]:
        counts["pending"] = employee_scope(user, User.objects.filter(status=UserStatus.PENDING, role=Role.EMPLOYEE)).count()
    if flags["applicants_manage"]:
        counts["applicants"] = JobApplication.objects.filter(status=ApplicationStatus.NEW).count()
    if flags["leads_manage"]:
        counts["leads"] = QuoteRequest.objects.filter(status=LeadStatus.NEW).count()
        counts["messages"] = ContactMessage.objects.filter(status=LeadStatus.NEW).count()
    if flags["emails_view"]:
        counts["emails_failed"] = EmailMessage.objects.filter(status=EmailStatus.FAILED).count()
    return counts


def build_nav(request):
    cached = getattr(request, "_bo_nav", None)
    if cached is not None:
        return cached
    user = request.user
    flags = {code.replace(".", "_"): has_permission(user, code) for code in FLAG_CODES}
    counts = _counts(request, flags)
    path = request.path
    groups, best, best_len = [], None, -1
    for heading, items in NAV:
        visible = []
        for key, label, url_name, icon, perm, badge, extra in items:
            if not has_permission(user, perm):
                continue
            try:
                url = reverse(url_name)
            except NoReverseMatch:  # optional areas (e.g. the practice lab) may not be installed
                continue
            prefixes = (url,) + tuple(extra)
            for p in prefixes:
                exact = p == reverse("backoffice:dashboard")
                hit = path == p if exact else path.startswith(p)
                if hit and len(p) > best_len:
                    best, best_len = key, len(p)
            visible.append({"key": key, "label": label, "url": url, "icon": icon, "count": counts.get(badge) if badge else None})
        if visible:
            groups.append({"heading": heading, "items": visible})
    nav = {"groups": groups, "active": best, "counts": counts, **flags}
    request._bo_nav = nav
    return nav


@register.simple_tag(takes_context=True)
def admin_nav(context):
    request = context.get("request")
    return build_nav(request) if request is not None else {}


@register.simple_tag(takes_context=True)
def asset_url(context, asset, download=False):
    request = context.get("request")
    if asset is None or request is None:
        return ""
    return media_url(asset, request.user, download=bool(download))


ACCEPT = {
    "video": "video/mp4,video/webm,video/quicktime,video/x-m4v,.mp4,.webm,.mov,.m4v",
    "image": "image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif",
    "document": ".pdf,.doc,.docx,.txt,.rtf,.odt,.zip,.csv,.xlsx,.json,.xml,.jpg,.jpeg,.png,.webp",
}
ACCEPT["media"] = ACCEPT["video"] + "," + ACCEPT["image"]


def _resolve_asset(value):
    if isinstance(value, MediaAsset):
        return value
    if not value:
        return None
    try:
        pk = uuid.UUID(str(value))
    except ValueError:
        return None
    return MediaAsset.objects.select_related("thumbnail").filter(pk=pk).first()


def _field_asset(field):
    """
    The asset to show in an upload widget — never a raw posted id that wasn't validated:
    unbound form → the saved value; bound form → the validated value, or (when that field
    failed validation) the saved value again.
    """
    form = field.form
    if not form.is_bound:
        return _resolve_asset(field.value())
    cleaned = getattr(form, "cleaned_data", None) or {}
    if field.name in cleaned and not field.errors:
        return _resolve_asset(cleaned[field.name])
    return _resolve_asset(form.get_initial_for_field(field.field, field.name))


@register.inclusion_tag("backoffice/components/uploader.html", takes_context=True)
def uploader(context, field, kind="video", purpose="", compact=False, external=None, note=True):
    request = context.get("request")
    asset = _field_asset(field)
    user = request.user if request else None
    url = media_url(asset, user) if asset and user else ""
    thumb = ""
    if asset is not None:
        if asset.kind == "image":
            thumb = url
        elif asset.thumbnail_id:
            thumb = media_url(asset.thumbnail, user)
    return {
        "field": field,
        "asset": asset,
        "asset_url": url,
        "thumb_url": thumb,
        "kind": kind,
        "purpose": purpose or kind,
        "accept": ACCEPT.get(kind, ""),
        "compact": compact,
        "external": (kind == "video") if external is None else external,
        "note": note,
    }


@register.filter
def bar_width(value, maximum):
    try:
        value, maximum = float(value or 0), float(maximum or 0)
    except (TypeError, ValueError):
        return 0
    if maximum <= 0:
        return 0
    return round(max(0.0, min(100.0, value / maximum * 100)), 1)


@register.filter
def clamp_pct(value):
    try:
        return round(max(0.0, min(100.0, float(value or 0))), 1)
    except (TypeError, ValueError):
        return 0


@register.filter
def sub(a, b):
    try:
        return a - b
    except TypeError:
        return ""
