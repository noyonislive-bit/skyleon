"""Small template helpers for the employee portal: {% load portal_tags %}."""

from datetime import datetime

from django import template
from django.utils import timezone
from django.utils.html import format_html

from apps.storage.services import media_url

register = template.Library()

SEVERITY_TONES = {"normal": "neutral", "important": "warning", "critical": "danger"}
KIND_ICONS = {"training": "graduation-cap", "feedback": "message-square-warning", "onboarding": "route", "qualification": "award"}

# ── Bangla labels for model choices shown in the portal ─────────────────────
# The models keep their English labels (admin panel); employees see these.
# Usage: {{ t.cadence|label_bn:"cadence" }} · {% status_badge p.status p.status|label_bn:"project_status" %}
CHOICE_LABELS_BN = {
    # training.Cadence
    "cadence": {
        "onboarding": "অনবোর্ডিং",
        "daily": "দৈনিক ট্রেনিং",
        "weekly": "সাপ্তাহিক ট্রেনিং",
        "reference": "রেফারেন্স",
    },
    # feedback.FeedbackCadence
    "feedback_cadence": {"daily": "দৈনিক", "weekly": "সাপ্তাহিক", "adhoc": "বিশেষ"},
    # feedback.Severity
    "severity": {"normal": "সাধারণ", "important": "গুরুত্বপূর্ণ", "critical": "জরুরি"},
    # assessments.TestKind
    "test_kind": {
        "training": "ট্রেনিং টেস্ট",
        "feedback": "ফিডব্যাক টেস্ট",
        "onboarding": "অনবোর্ডিং টেস্ট",
        "qualification": "কোয়ালিফিকেশন টেস্ট",
    },
    # assessments.QuestionType
    "question_type": {
        "single": "একটি উত্তর",
        "multi": "একাধিক উত্তর",
        "true_false": "সত্য / মিথ্যা",
    },
    # projects.MemberRole
    "member_role": {
        "annotator": "অ্যানোটেটর",
        "reviewer": "রিভিউয়ার",
        "qa": "QA",
        "team_lead": "টিম লিড",
        "manager": "প্রজেক্ট ম্যানেজার",
        "trainer": "ট্রেইনার",
    },
    # projects.ProjectStatus
    "project_status": {
        "planning": "পরিকল্পনা চলছে",
        "active": "চলমান",
        "paused": "সাময়িক বন্ধ",
        "completed": "সম্পন্ন",
        "archived": "আর্কাইভ করা",
    },
    # accounts.Role
    "user_role": {
        "super_admin": "সুপার অ্যাডমিন",
        "project_manager": "প্রজেক্ট ম্যানেজার",
        "trainer": "ট্রেইনার / QA",
        "employee": "এমপ্লয়ি",
        "client": "ক্লায়েন্ট",
    },
    # accounts.UserStatus
    "user_status": {"pending": "অনুমোদনের অপেক্ষায়", "active": "সক্রিয়", "suspended": "স্থগিত"},
    # core.ProgressStatus
    "progress": {"not_started": "শুরু হয়নি", "in_progress": "চলছে", "completed": "সম্পন্ন"},
    # comms.NotificationType
    "notification": {
        "training": "ট্রেনিং",
        "feedback": "ফিডব্যাক",
        "test": "টেস্ট",
        "announcement": "ঘোষণা",
        "meeting": "মিটিং",
        "account": "অ্যাকাউন্ট",
        "project": "প্রজেক্ট",
        "system": "সিস্টেম",
    },
    # training.OnboardingStepType
    "step_type": {
        "welcome": "স্বাগতম / প্রজেক্ট পরিচিতি",
        "guideline_video": "প্রজেক্ট গাইডলাইন ভিডিও",
        "tutorial": "অ্যানোটেশন টিউটোরিয়াল",
        "examples": "সঠিক কাজের উদাহরণ",
        "common_mistakes": "সাধারণ ভুলগুলো",
        "qa_guidelines": "QA / রিভিউ গাইডলাইন",
        "test": "ট্রেনিং টেস্ট",
        "qualification": "ফাইনাল কোয়ালিফিকেশন",
        "custom": "অন্যান্য ধাপ",
    },
}


def choice_bn(group, value) -> str:
    """Bangla label for a choice value; unknown values fall back to a readable version of the value."""
    key = str(value or "")
    return CHOICE_LABELS_BN.get(group, {}).get(key) or key.replace("_", " ").capitalize()


@register.filter
def label_bn(value, group):
    return choice_bn(group, value)


# ── Relative times in Bangla ("3 ঘণ্টা আগে", "2 দিন পরে") ─────────────────────
# Django's `timesince` has no Bangla translation, so the portal uses these instead.
TIME_UNITS_BN = (
    ("বছর", 365 * 86400),
    ("মাস", 30 * 86400),
    ("সপ্তাহ", 7 * 86400),
    ("দিন", 86400),
    ("ঘণ্টা", 3600),
    ("মিনিট", 60),
)


def _span_bn(seconds: float, depth: int = 2) -> str:
    """Largest unit plus the next one when it is non-zero (like Django's timesince): '3 ঘণ্টা 5 মিনিট'."""
    remaining = int(max(0, seconds))
    counts = []
    for name, size in TIME_UNITS_BN:
        n, remaining = divmod(remaining, size)
        counts.append((name, n))
    first = next((i for i, (_, n) in enumerate(counts) if n), None)
    if first is None:
        return ""
    parts = []
    for name, n in counts[first:first + depth]:
        if not n:
            break
        parts.append(f"{n} {name}")
    return " ".join(parts)


def _as_datetime(value):
    if not isinstance(value, datetime):
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


@register.filter
def bn_ago(value):
    """datetime → '3 ঘণ্টা আগে' (or 'এইমাত্র' under a minute)."""
    value = _as_datetime(value)
    if value is None:
        return ""
    span = _span_bn((timezone.now() - value).total_seconds())
    return f"{span} আগে" if span else "এইমাত্র"


@register.filter
def bn_until(value):
    """datetime → '2 দিন 3 ঘণ্টা পরে' (or 'এখনই' under a minute)."""
    value = _as_datetime(value)
    if value is None:
        return ""
    span = _span_bn((value - timezone.now()).total_seconds())
    return f"{span} পরে" if span else "এখনই"


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
    return format_html('<span class="badge badge-{}">{}</span>', tone, choice_bn("severity", feedback.severity))


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


# The default tutorial categories (seed_demo CATEGORIES) are stored in English for the admin panel;
# employees see them in Bangla. Categories an admin adds show as they were named.
CATEGORY_BN = {
    "Getting started": "শুরুর পাঠ",
    "Project guidelines": "প্রজেক্ট গাইডলাইন",
    "Annotation techniques": "অ্যানোটেশনের কৌশল",
    "QA & review": "QA ও রিভিউ",
    "Tools & platforms": "টুল ও প্ল্যাটফর্ম",
    "Daily training": "দৈনিক ট্রেনিং",
}


@register.filter
def category_bn(name):
    return CATEGORY_BN.get(name, name)
