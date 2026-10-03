from datetime import timedelta

from django.db.models import (
    Avg,
    CharField,
    Count,
    FloatField,
    OuterRef,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone

from apps.assessments.models import TestAttempt
from apps.comms.models import Meeting
from apps.core.choices import ProgressStatus
from apps.training.models import TutorialProgress
from apps.training.services import onboarding_for_user

from ..helpers import tests_with_state
from ..scope import portal_view

NEW_DAYS = 7


def greeting(now) -> str:
    hour = timezone.localtime(now).hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def annotate_progress(qs, user):
    """Annotate tutorials with the user's progress status/percent (one query, no N+1)."""
    progress = TutorialProgress.objects.filter(tutorial=OuterRef("pk"), user=user)
    return qs.annotate(
        my_status=Coalesce(
            Subquery(progress.values("status")[:1]), Value(ProgressStatus.NOT_STARTED), output_field=CharField()
        ),
        my_percent=Coalesce(Subquery(progress.values("percent")[:1]), Value(0.0), output_field=FloatField()),
    )


def upcoming_meetings(user, now, limit=None):
    qs = (
        Meeting.objects.filter(invites__user=user, starts_at__gte=now - timedelta(hours=8))
        .select_related("project")
        .order_by("starts_at")
    )
    result = []
    for m in qs:
        m.ends_at = m.starts_at + timedelta(minutes=m.duration_min or 0)
        if m.ends_at < now:
            continue
        m.is_live = m.starts_at <= now <= m.ends_at
        result.append(m)
        if limit and len(result) >= limit:
            break
    return result


@portal_view
def dashboard(request):
    scope, user, now = request.portal, request.user, timezone.now()

    # Onboarding (per project section) ------------------------------------
    onboarding = onboarding_for_user(user)
    for sec in onboarding:
        sec["next"] = next((i for i in sec["steps"] if not i["done_at"]), None)
    onboarding_by_project = {sec["project"].pk if sec["project"] else None: sec for sec in onboarding}
    projects = [{"member": m, "onboarding": onboarding_by_project.get(m.project_id)} for m in scope.memberships]

    # Training --------------------------------------------------------------
    tutorials = annotate_progress(scope.tutorials(), user)
    done = Q(my_status=ProgressStatus.COMPLETED)
    stats = tutorials.aggregate(
        required_total=Count("pk", filter=Q(is_required=True)),
        required_done=Count("pk", filter=Q(is_required=True) & done),
        all_done=Count("pk", filter=done),
        all_total=Count("pk"),
    )
    stats["required_percent"] = (
        round(stats["required_done"] / stats["required_total"] * 100) if stats["required_total"] else 100
    )
    new_tutorials = list(
        tutorials.filter(published_at__gte=now - timedelta(days=NEW_DAYS))
        .exclude(done)
        .select_related("project", "category", "video", "video__thumbnail")
        .order_by("-published_at")[:4]
    )
    continue_watching = list(
        tutorials.filter(my_status=ProgressStatus.IN_PROGRESS)
        .select_related("project", "category", "video")
        .order_by("-published_at")[:3]
    )

    # Feedback --------------------------------------------------------------
    recipients = scope.recipients()
    unseen_feedback = list(
        recipients.filter(first_viewed_at__isnull=True)
        .select_related("feedback", "feedback__project", "feedback__team")
        .order_by("-feedback__published_at")[:5]
    )
    fb_stats = recipients.aggregate(total=Count("pk"), watched=Count("pk", filter=Q(watched_at__isnull=False)))
    watched_rate = round(fb_stats["watched"] / fb_stats["total"] * 100) if fb_stats["total"] else None

    # Tests -----------------------------------------------------------------
    test_rows = tests_with_state(scope)
    pending_tests = sorted(
        (r for r in test_rows if r["is_open"]),
        key=lambda r: (r["due_at"] is None, r["due_at"] or now, r["test"].title),
    )[:5]
    attempts = TestAttempt.objects.filter(user=user, submitted_at__isnull=False)
    recent_attempts = list(attempts.select_related("test").order_by("-submitted_at")[:4])
    test_stats = attempts.aggregate(avg=Avg("score"), taken=Count("pk"), passed=Count("pk", filter=Q(passed=True)))

    # Comms -----------------------------------------------------------------
    announcements = list(
        scope.announcements().select_related("project").annotate(is_read=scope.announcement_read())[:3]
    )
    meetings = upcoming_meetings(user, now, limit=3)

    return render(request, "portal/dashboard.html", {
        "greeting": greeting(now),
        "now": now,
        "projects": projects,
        "onboarding": onboarding,
        "onboarding_open": [s for s in onboarding if not s["completed"]],
        "stats": stats,
        "new_tutorials": new_tutorials,
        "continue_watching": continue_watching,
        "unseen_feedback": unseen_feedback,
        "fb_stats": fb_stats,
        "watched_rate": watched_rate,
        "pending_tests": pending_tests,
        "recent_attempts": recent_attempts,
        "test_stats": test_stats,
        "announcements": announcements,
        "meetings": meetings,
        "new_days": NEW_DAYS,
    })
