"""Small helpers shared by the portal views."""

import json
import math
from dataclasses import dataclass, field

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.utils.http import url_has_allowed_host_and_scheme

from apps.assessments.models import TestAssignment
from apps.assessments.services import test_state
from apps.storage.models import MediaStatus
from apps.storage.services import media_url
from apps.training.progress import JITTER_SECONDS, MAX_PLAYBACK_RATE

from .scope import attempts_by_test

MAX_CLIENT_DURATION = 6 * 60 * 60  # seconds — bound for client-reported durations
RESTART_AT = 0.95  # resume from the start when the last position is past 95 %


def crumbs(*items):
    """[("ট্রেনিং", url), ("Title", None)] → breadcrumb list for templates/portal/base.html."""
    return [{"label": label, "url": url} for label, url in items]


def paginate(request, qs, per_page=20):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


def read_json(request) -> dict:
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def safe_internal_path(link: str, request) -> str | None:
    """Only same-site absolute paths ("/portal/…"), never protocol-relative or external URLs."""
    link = (link or "").strip()
    if not link.startswith("/") or link.startswith("//") or link.startswith("/\\"):
        return None
    if not url_has_allowed_host_and_scheme(link, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return None
    return link


def trusted_duration(asset, reported) -> float | None:
    """The asset's stored duration — never the browser's word for it.

    Staff uploads and MP4 links store the duration measured in the staff member's browser. For the
    rare asset without one (e.g. some HLS links) the first viewer's reported duration is stored once
    and then used for everybody, so it can't be changed per request afterwards.
    """
    if asset is not None and asset.duration_sec:
        return float(asset.duration_sec)
    try:
        value = float(reported)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    value = min(value, MAX_CLIENT_DURATION)
    if asset is not None:
        type(asset).objects.filter(pk=asset.pk, duration_sec__isnull=True).update(duration_sec=value)
        asset.refresh_from_db(fields=["duration_sec"])
        return float(asset.duration_sec or value)
    return value


# ── Tracked video player ─────────────────────────────────────────────────────

MIN_HEARTBEAT_INTERVAL = 3.0  # seconds between recorded heartbeats for one row


def heartbeat_allowed(row, now) -> bool:
    """
    Defence in depth on top of training.progress (which caps new coverage per heartbeat):
      * at most one recorded heartbeat every few seconds per progress row, and
      * total coverage can never run ahead of 2× the wall-clock time since the video was first opened.
    A skipped heartbeat loses nothing — the browser re-sends all played ranges next time.
    """
    last = row.last_heartbeat_at
    if last is not None and (now - last).total_seconds() < MIN_HEARTBEAT_INTERVAL:
        return False
    first = row.first_viewed_at
    if first is not None:
        ceiling = (max(0.0, (now - first).total_seconds()) + JITTER_SECONDS) * MAX_PLAYBACK_RATE
        if (row.watched_seconds or 0) >= ceiling:
            return False
    return True


@dataclass
class PlayerConfig:
    state: str  # ready | missing | processing | failed
    src: str = ""
    is_hls: bool = False
    mime: str = ""
    poster: str = ""
    heartbeat_url: str = ""
    duration: float | None = None
    resume: float = 0
    furthest: float = 0
    enforce: bool = False
    percent: float = 0
    completed: bool = False
    watched_seconds: float = 0
    threshold: int = field(default_factory=lambda: int(settings.VIDEO_COMPLETION_THRESHOLD))

    @property
    def ready(self):
        return self.state == "ready"


def player_config(asset, user, *, heartbeat_url, row, enforce, completed) -> PlayerConfig:
    """
    Build the data for templates/portal/includes/player.html from a progress row
    (TutorialProgress or FeedbackRecipient — both have watched_ranges/percent/last_position_sec).
    """
    if asset is None:
        return PlayerConfig(state="missing")
    if asset.status == MediaStatus.FAILED:
        return PlayerConfig(state="failed")
    if asset.status != MediaStatus.READY:
        return PlayerConfig(state="processing")
    src = media_url(asset, user)
    if not src:
        return PlayerConfig(state="processing")
    ranges = row.watched_ranges or []
    furthest = 0.0
    for r in ranges:
        try:
            furthest = max(furthest, float(r[1]))
        except (TypeError, ValueError, IndexError):
            continue
    duration = float(asset.duration_sec) if asset.duration_sec else None
    resume = float(row.last_position_sec or 0)
    if duration and resume >= duration * RESTART_AT:
        resume = 0.0
    if enforce:
        resume = min(resume, furthest)
    thumb = asset.thumbnail if asset.thumbnail_id else None
    return PlayerConfig(
        state="ready",
        src=src,
        is_hls=asset.is_hls,
        mime="" if asset.is_hls else (asset.mime_type or "video/mp4"),
        poster=media_url(thumb, user) if thumb else "",
        heartbeat_url=heartbeat_url,
        duration=duration,
        resume=round(resume, 2),
        furthest=round(furthest, 2),
        enforce=enforce,
        percent=row.percent or 0,
        completed=completed,
        watched_seconds=row.watched_seconds or 0,
    )


# ── Tests ────────────────────────────────────────────────────────────────────

# Test state → badge label (Bangla, see docs/BANGLA_STYLE.md).
STATUS_LABELS = {
    "pending": "শুরু হয়নি",
    "in_progress": "চলছে",
    "passed": "পাস",
    "review": "পাস হয়নি",
    "locked": "আর চেষ্টা নেই",
}
STATUS_TONES = {"pending": "warning", "in_progress": "info", "passed": "success", "review": "danger", "locked": "neutral"}
OPEN_STATUSES = {"pending", "in_progress", "review"}


def state_badge(state) -> dict:
    return {"label": STATUS_LABELS.get(state.status, state.status), "tone": STATUS_TONES.get(state.status, "neutral")}


def tests_with_state(scope, qs=None):
    """
    [{"test", "state", "badge", "due_at", "feedback", "recipient"}] for the visible tests (or `qs`),
    using two extra queries in total (attempts + assignments).
    """
    qs = qs if qs is not None else scope.tests()
    tests = list(
        qs.select_related("project", "feedback").annotate(
            question_count=Count("questions", distinct=True), total_points=Sum("questions__points")
        )
    )
    ids = [t.pk for t in tests]
    attempts = attempts_by_test(scope.user, ids)
    due = dict(TestAssignment.objects.filter(user=scope.user, test_id__in=ids).values_list("test_id", "due_at"))
    fb_ids = [t.feedback.pk for t in tests if getattr(t, "feedback", None)]
    recipients = (
        {r.feedback_id: r for r in scope.recipients().filter(feedback_id__in=fb_ids)} if fb_ids else {}
    )
    out = []
    for t in tests:
        state = test_state(scope.user, t, attempts=attempts.get(t.pk, []))
        fb = getattr(t, "feedback", None)
        recipient = recipients.get(fb.pk) if fb else None
        out.append({
            "test": t,
            "state": state,
            "badge": state_badge(state),
            "due_at": due.get(t.pk) or (fb.due_at if fb else None),
            "feedback": fb,
            "recipient": recipient,
            "needs_video": bool(fb and (recipient is None or not recipient.watched_at)),
            "is_open": state.status in OPEN_STATUSES,
        })
    return out


def feedback_gate(scope, test):
    """
    Feedback tests unlock only after the feedback video was watched.
    Returns (recipient_or_None, reason_or_None).
    """
    fb = getattr(test, "feedback", None)
    if fb is None:
        return None, None
    recipient = scope.recipients().filter(feedback=fb).first()
    if recipient is None:
        return None, "এই টেস্টটি এমন একটি ফিডব্যাকের, যা আপনাকে পাঠানো হয়নি।"
    if not recipient.watched_at:
        return recipient, "আগে ফিডব্যাক ভিডিওটি দেখুন — দেখা হলেই টেস্ট খুলে যাবে।"
    return recipient, None
