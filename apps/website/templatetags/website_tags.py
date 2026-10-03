"""Small template helpers for the public website: {% load website_tags %}."""

import re

from django import template

register = template.Library()


@register.filter
def tel_href(value):
    """'+1 (555) 010-2000' → 'tel:+15550102000'."""
    raw = str(value or "").strip()
    digits = re.sub(r"[^\d]", "", raw)
    return f"tel:{'+' if raw.startswith('+') else ''}{digits}" if digits else ""


@register.filter
def whatsapp_href(value):
    """A phone number or an existing wa.me / https link → WhatsApp URL."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("http"):
        return raw
    digits = re.sub(r"[^\d]", "", raw)
    return f"https://wa.me/{digits}" if digits else ""


@register.filter
def zfill2(value):
    try:
        return f"{int(value):02d}"
    except (TypeError, ValueError):
        return value


@register.filter
def pct_span(span, total=12):
    """Width percentage for a timeline segment: span / total."""
    try:
        return f"{(float(span) / float(total)) * 100:.3f}"
    except (TypeError, ValueError, ZeroDivisionError):
        return "0"


@register.simple_tag
def website_nav():
    """Navigation data for the header and footer."""
    from apps.website import content

    return {
        "services": content.SERVICES,
        "solutions": content.SOLUTION_PAGES,
        "industries": content.INDUSTRIES,
    }
