"""
Aggregated progress figures for lists of users — one GROUP BY query per
metric so tables never run per-row queries.

Every function accepts `project_ids`: None for "everything", or a list of
project ids (company-wide content, project NULL, is always included).
"""

from collections import defaultdict

from django.db.models import Avg, Count, Max, Q

from apps.assessments.models import TestAttempt
from apps.core.choices import ContentStatus, ProgressStatus
from apps.feedback.models import FeedbackRecipient
from apps.training.models import TutorialProgress

from .helpers import pct


def _in_scope(field, project_ids):
    if project_ids is None:
        return Q()
    return Q(**{f"{field}__in": project_ids}) | Q(**{f"{field}__isnull": True})


def training_by_user(user_ids, project_ids=None, only_project=None):
    """Required + assigned + published tutorials → {uid: {done, total, percent}}."""
    qs = TutorialProgress.objects.filter(
        user_id__in=list(user_ids), assigned=True, tutorial__is_required=True, tutorial__status=ContentStatus.PUBLISHED
    ).filter(_in_scope("tutorial__project", project_ids))
    if only_project is not None:
        qs = qs.filter(tutorial__project=only_project)
    out = {}
    for row in qs.values("user_id").annotate(
        total=Count("id"), done=Count("id", filter=Q(status=ProgressStatus.COMPLETED)), last=Max("last_viewed_at")
    ):
        out[row["user_id"]] = {"done": row["done"], "total": row["total"], "percent": pct(row["done"], row["total"]), "last": row["last"]}
    return out


def feedback_by_user(user_ids, project_ids=None):
    """{uid: {received, seen, watched, acknowledged, watched_pct, tests_total, tests_passed, last}}"""
    user_ids = list(user_ids)
    qs = FeedbackRecipient.objects.filter(user_id__in=user_ids, feedback__status=ContentStatus.PUBLISHED).filter(
        _in_scope("feedback__project", project_ids)
    )
    out = defaultdict(lambda: {"received": 0, "seen": 0, "watched": 0, "acknowledged": 0, "tests_total": 0, "tests_passed": 0, "last": None})
    rows = list(qs.values_list("user_id", "feedback__test_id", "first_viewed_at", "watched_at", "acknowledged_at"))
    test_ids = {r[1] for r in rows if r[1]}
    passed = set(
        TestAttempt.objects.filter(user_id__in=user_ids, test_id__in=test_ids, passed=True).values_list("user_id", "test_id")
    ) if test_ids else set()
    for uid, test_id, seen, watched, acked in rows:
        s = out[uid]
        s["received"] += 1
        s["seen"] += 1 if seen else 0
        s["watched"] += 1 if watched else 0
        s["acknowledged"] += 1 if acked else 0
        if seen and (s["last"] is None or seen > s["last"]):
            s["last"] = seen
        if test_id:
            s["tests_total"] += 1
            if (uid, test_id) in passed:
                s["tests_passed"] += 1
    for s in out.values():
        s["watched_pct"] = pct(s["watched"], s["received"])
    return dict(out)


def tests_by_user(user_ids, project_ids=None):
    """Submitted attempts → {uid: {attempted, passed, attempts, avg, last}} (attempted/passed are distinct tests)."""
    qs = TestAttempt.objects.filter(user_id__in=list(user_ids), submitted_at__isnull=False).filter(
        _in_scope("test__project", project_ids)
    )
    out = {}
    for row in qs.values("user_id").annotate(
        attempted=Count("test", distinct=True),
        passed=Count("test", filter=Q(passed=True), distinct=True),
        attempts=Count("id"),
        avg=Avg("score"),
        last=Max("submitted_at"),
    ):
        out[row["user_id"]] = row
    return out


def latest(*values):
    values = [v for v in values if v]
    return max(values) if values else None
