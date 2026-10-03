from django.contrib import messages
from django.db import transaction
from django.db.models import Avg, Count, Exists, OuterRef, Q, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from apps.assessments.models import TestAttempt
from apps.assessments.services import test_state
from apps.feedback.models import FeedbackRecipient
from apps.feedback.services import mark_opened, record_feedback_heartbeat

from ..helpers import crumbs, heartbeat_allowed, paginate, player_config, read_json, state_badge, trusted_duration
from ..scope import portal_api, portal_view

TABS = [
    ("new", "New"),
    ("pending", "Pending"),
    ("completed", "Completed"),
    ("all", "All"),
]


def annotate_recipients(qs, user):
    """Adds test_passed / test_taken / best_score for the feedback's linked test (no N+1)."""
    attempts = TestAttempt.objects.filter(test_id=OuterRef("feedback__test_id"), user=user, submitted_at__isnull=False)
    return qs.annotate(
        test_passed=Exists(attempts.filter(passed=True)),
        test_taken=Exists(attempts),
        best_score=Subquery(attempts.order_by("-score").values("score")[:1]),
    )


def tab_filters():
    completed = Q(first_viewed_at__isnull=False, watched_at__isnull=False) & (
        Q(feedback__test__isnull=True) | Q(test_passed=True)
    )
    return {
        "new": Q(first_viewed_at__isnull=True),
        "pending": Q(first_viewed_at__isnull=False) & ~completed,
        "completed": completed,
        "all": Q(),
    }


@portal_view
def feedback_list(request):
    scope, user = request.portal, request.user
    filters = tab_filters()
    tab = request.GET.get("tab")
    base = annotate_recipients(scope.recipients(), user)
    counts = base.aggregate(**{key: Count("pk", filter=q) for key, q in filters.items()})
    if tab not in filters:
        tab = "new" if counts["new"] else "all"
    qs = (
        base.filter(filters[tab])
        .select_related("feedback", "feedback__project", "feedback__team", "feedback__test")
        .order_by("-feedback__published_at", "-feedback__number")
    )
    page = paginate(request, qs, 20)
    test_summary = TestAttempt.objects.filter(
        user=user, submitted_at__isnull=False, test__feedback__isnull=False
    ).aggregate(taken=Count("pk"), passed=Count("pk", filter=Q(passed=True)), avg=Avg("score"))
    pending_tests = base.filter(feedback__test__isnull=False, test_passed=False).count()
    return render(request, "portal/feedback_list.html", {
        "tab": tab,
        "tabs": [{"key": k, "label": label, "count": counts[k]} for k, label in TABS],
        "page": page,
        "counts": counts,
        "test_summary": test_summary,
        "pending_feedback_tests": pending_tests,
        "page_title": "My feedback",
        "page_subtitle": "QA feedback from your trainers. Watch each video, read the explanation and take the short test.",
        "crumbs": crumbs(("My feedback", None)),
    })


def _recipient_or_404(scope, number):
    return get_object_or_404(
        scope.recipients().select_related(
            "feedback", "feedback__project", "feedback__team", "feedback__video", "feedback__video__thumbnail",
            "feedback__test", "feedback__created_by",
        ),
        feedback__number=number,
    )


@portal_view
def feedback_detail(request, number):
    scope, user = request.portal, request.user
    recipient = _recipient_or_404(scope, number)
    fb = recipient.feedback
    was_new = recipient.first_viewed_at is None
    mark_opened(recipient, has_video=bool(fb.video_id))

    player = None
    if fb.video_id:
        player = player_config(
            fb.video, user,
            heartbeat_url=reverse("portal:feedback_heartbeat", args=[fb.number]),
            row=recipient, enforce=not recipient.watched_at, completed=bool(recipient.watched_at),
        )

    test = fb.test if fb.test_id and fb.test.is_published else None
    state = badge = None
    attempts = []
    if test:
        attempts = list(TestAttempt.objects.filter(test=test, user=user).order_by("-attempt_number"))
        state = test_state(user, test, attempts=attempts)
        badge = state_badge(state)
        attempts = [a for a in attempts if a.submitted_at]

    return render(request, "portal/feedback_detail.html", {
        "recipient": recipient,
        "fb": fb,
        "was_new": was_new,
        "player": player,
        "test": test,
        "state": state,
        "badge": badge,
        "attempts": attempts,
        "question_count": test.questions.count() if test else 0,
        "crumbs": crumbs(("My feedback", reverse("portal:feedback")), (fb.display_number, None)),
    })


@require_POST
@portal_view
def feedback_ack(request, number):
    recipient = _recipient_or_404(request.portal, number)
    if not recipient.acknowledged_at:
        recipient.acknowledged_at = timezone.now()
        recipient.save(update_fields=["acknowledged_at"])
        messages.success(request, f"Thanks — feedback {recipient.feedback.display_number} acknowledged.")
    return redirect("portal:feedback_detail", number=number)


@portal_api
def feedback_heartbeat(request, number):
    scope = request.portal
    recipient = scope.recipients().select_related("feedback", "feedback__video").filter(feedback__number=number).first()
    if recipient is None:
        return JsonResponse({"error": "not found"}, status=404)
    video = recipient.feedback.video
    if video is None:
        return JsonResponse({"error": "this feedback has no video"}, status=400)
    data = read_json(request)
    duration = trusted_duration(video, data.get("duration"))
    if duration is None:
        return JsonResponse({"error": "unknown duration"}, status=400)
    throttled = False
    with transaction.atomic():
        recipient = FeedbackRecipient.objects.select_for_update().get(pk=recipient.pk)
        if heartbeat_allowed(recipient, timezone.now()):
            recipient = record_feedback_heartbeat(
                recipient, duration=duration, ranges=data.get("ranges"), position=data.get("position")
            )
        else:
            throttled = True
    watched_at = timezone.localtime(recipient.watched_at) if recipient.watched_at else None
    return JsonResponse({
        "percent": round(recipient.percent, 1),
        "watched_seconds": round(recipient.watched_seconds, 1),
        "position": recipient.last_position_sec,
        "status": "completed" if watched_at else ("in_progress" if recipient.watched_seconds else "not_started"),
        "completed": bool(watched_at),
        "throttled": throttled,
        "completed_at": date_format(watched_at, "M j, Y · H:i") if watched_at else None,
    })
