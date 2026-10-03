"""Small template helpers for the employee portal: {% load portal_tags %}."""

from django import template
from django.utils.html import format_html

from apps.storage.services import media_url

register = template.Library()

SEVERITY_TONES = {"normal": "neutral", "important": "warning", "critical": "danger"}
KIND_ICONS = {"training": "graduation-cap", "feedback": "message-square-warning", "onboarding": "route", "qualification": "award"}


@register.simple_tag(takes_context=True)
def thumbnail_url(context, asset):
    """Signed URL of a video's thumbnail (select_related('video__thumbnail') to avoid extra queries)."""
    request = context.get("request")
    if asset is None or not getattr(asset, "thumbnail_id", None) or request is None:
        return ""
    return media_url(asset.thumbnail, request.user)


@register.simple_tag
def severity_badge(feedback):
    tone = SEVERITY_TONES.get(feedback.severity, "neutral")
    return format_html('<span class="badge badge-{}">{}</span>', tone, feedback.get_severity_display())


@register.simple_tag
def tone_badge(tone, label):
    return format_html('<span class="badge badge-{}">{}</span>', tone or "neutral", label)


@register.filter
def kind_icon(kind):
    return KIND_ICONS.get(kind, "clipboard-check")


@register.filter
def pct(value):
    """Clamp to an integer 0–100 for inline widths / CSS variables."""
    try:
        return max(0, min(100, int(round(float(value or 0)))))
    except (TypeError, ValueError):
        return 0


@register.simple_tag(takes_context=True)
def portal_counts(context):
    """
    Sidebar / top-bar counts for any page extending portal/base.html — also pages rendered by
    views outside apps.portal that don't use @portal_view (the scope is created and cached on the request).
    """
    from apps.accounts.permissions import has_permission

    from ..scope import PortalScope

    request = context.get("request")
    if request is None:
        return {}
    scope = getattr(request, "portal", None)
    if scope is None:
        if not has_permission(request.user, "portal.access"):
            return {}
        scope = request.portal = PortalScope(request.user)
    return scope.counts


@register.filter
def letter(index):
    """1 → A, 2 → B … (option keys in the test taker)."""
    try:
        n = int(index)
    except (TypeError, ValueError):
        return ""
    return chr(64 + n) if 1 <= n <= 26 else str(n)
