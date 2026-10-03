"""
Company information shown on the public website and in emails.
Defaults live here; Admin → Settings stores overrides in SiteSetting("company").
"""

from django.conf import settings
from django.core.cache import cache

from .models import SiteSetting

BRAND = {
    "name": "Skyloon AI",
    "legal_name": "Skyloon AI",
    "tagline": "AI Data Annotation & Video Data Services",
    "description": (
        "Reliable image, video, text and multimodal annotation services powered by skilled teams, "
        "structured workflows and dedicated quality control."
    ),
}

DEFAULT_COMPANY = {
    "email": "hello@skyloon.ai",
    "careers_email": "careers@skyloon.ai",
    "phone": "",
    "whatsapp": "",
    "address": "",
    "business_hours": "Monday – Saturday, 9:00 – 18:00",
    "show_map": False,
    "map_embed_url": "",
    "linkedin": "",
    "facebook": "",
    "x": "",
    "youtube": "",
}

DEFAULT_NOTIFICATIONS = {
    # Extra addresses that receive quote / application / signup alerts.
    "admin_emails": [],
}

CACHE_KEY = "site_settings:v1"


def _load() -> dict:
    data = cache.get(CACHE_KEY)
    if data is None:
        data = {s.key: s.value for s in SiteSetting.objects.all()}
        cache.set(CACHE_KEY, data, 300)
    return data


def get_setting(key: str, default: dict) -> dict:
    stored = _load().get(key) or {}
    return {**default, **stored} if isinstance(stored, dict) else default


def set_setting(key: str, value: dict) -> None:
    SiteSetting.objects.update_or_create(key=key, defaults={"value": value})
    cache.delete(CACHE_KEY)


def company() -> dict:
    return get_setting("company", DEFAULT_COMPANY)


def notification_settings() -> dict:
    return get_setting("notifications", DEFAULT_NOTIFICATIONS)


def admin_notification_emails() -> list[str]:
    emails = list(settings.ADMIN_NOTIFICATION_EMAILS) + list(notification_settings().get("admin_emails") or [])
    seen, result = set(), []
    for e in emails:
        e = (e or "").strip().lower()
        if e and e not in seen:
            seen.add(e)
            result.append(e)
    return result
