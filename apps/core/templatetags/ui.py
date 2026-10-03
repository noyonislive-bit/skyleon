"""
Template helpers available in every template (registered as a builtin):

  {% icon "check" class="h-4 w-4" %}            inline Lucide icon
  {% brand_icon "linkedin" class="h-4 w-4" %}   filled brand mark
  {{ text|markdown }}                            safe Markdown → HTML
  {{ seconds|duration }}                         125 → 2:05
  {{ value|percent }}                            87.5 → 88%
  {{ bytes|filesize_h }}                         1048576 → 1.0 MB
  {% status_badge obj.status %}                  coloured badge for any status value
  {% nav_active "/portal/training" %}            "is-active" when current path matches
  {{ form.field|add_class:"input" }}             add CSS classes to a widget
"""

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.core.icons import BRAND_ICONS, ICONS
from apps.core.markdown import render_markdown

register = template.Library()


@register.simple_tag
def icon(name, **attrs):
    body = ICONS.get(name) or ICONS["circle"]
    css = attrs.pop("class", "h-5 w-5")
    stroke = attrs.pop("stroke_width", "1.75")
    extra = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" class="{css}" aria-hidden="true" {extra}>'
        f"{body}</svg>"
    )


@register.simple_tag
def brand_icon(name, **attrs):
    body = BRAND_ICONS.get(name, "")
    css = attrs.pop("class", "h-5 w-5")
    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="{css}" aria-hidden="true">{body}</svg>'
    )


@register.filter(name="markdown", is_safe=True)
def markdown_filter(text):
    return mark_safe(render_markdown(text))


@register.filter
def duration(seconds):
    if seconds is None or seconds == "":
        return "—"
    t = max(0, int(round(float(seconds))))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@register.filter
def percent(value, digits=0):
    if value is None or value == "":
        return "—"
    return f"{float(value):.{int(digits)}f}%"


@register.filter
def filesize_h(num):
    if num in (None, ""):
        return "—"
    n = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def add_class(field, css):
    existing = field.field.widget.attrs.get("class", "")
    return field.as_widget(attrs={"class": f"{existing} {css}".strip()})


# Status → badge tone. Used for any *.status / state string across the app.
BADGE_TONES = {
    # positive
    "active": "success", "published": "success", "completed": "success", "passed": "success", "approved": "success",
    "won": "success", "ready": "success", "sent": "success", "watched": "success", "qualified": "success",
    # in progress / attention
    "pending": "warning", "in_progress": "info", "reviewing": "info", "shortlisted": "info", "contacted": "info",
    "proposal": "info", "planning": "info", "review": "warning", "uploading": "info", "new": "brand",
    "unseen": "warning", "important": "warning", "draft": "neutral", "not_started": "neutral", "paused": "warning",
    # negative
    "suspended": "danger", "failed": "danger", "rejected": "danger", "lost": "danger", "critical": "danger",
    "archived": "neutral", "not_watched": "danger",
}


@register.simple_tag
def status_badge(value, label=None):
    key = str(value or "").lower()
    tone = BADGE_TONES.get(key, "neutral")
    text = label or key.replace("_", " ").capitalize() or "—"
    return format_html('<span class="badge badge-{}">{}</span>', tone, text)


@register.simple_tag(takes_context=True)
def nav_active(context, prefix, exact=False):
    request = context.get("request")
    if not request:
        return ""
    path = request.path
    match = path == prefix if exact else (path == prefix or path.startswith(prefix.rstrip("/") + "/"))
    return "is-active" if match else ""


@register.filter
def initials(name):
    parts = [p for p in str(name or "").split() if p][:2]
    return "".join(p[0].upper() for p in parts) or "?"


@register.filter
def split(value, sep=","):
    return [v.strip() for v in str(value or "").split(sep) if v.strip()]
