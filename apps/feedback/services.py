"""Publishing QA feedback to a project/team and tracking who has seen it."""

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.assessments.services import assign_test
from apps.comms.models import NotificationType
from apps.comms.services import notify
from apps.core.audience import project_audience
from apps.core.choices import ContentStatus
from apps.training.progress import apply_heartbeat

from .models import Feedback, FeedbackRecipient


def add_recipients(feedback: Feedback, users, *, notify_users=True) -> int:
    users = list(users)
    existing = set(FeedbackRecipient.objects.filter(feedback=feedback, user__in=users).values_list("user_id", flat=True))
    new = [u for u in users if u.pk not in existing]
    FeedbackRecipient.objects.bulk_create([FeedbackRecipient(feedback=feedback, user=u) for u in new], ignore_conflicts=True)
    if feedback.test_id and new:
        assign_test(feedback.test, new, notify_users=False)
    if notify_users and new:
        notify(
            new, NotificationType.FEEDBACK, f"নতুন ফিডব্যাক {feedback.display_number}: {feedback.topic}",
            "আপনার জন্য নতুন একটি ফিডব্যাক ভিডিও এসেছে।" if feedback.video_id else "আপনার জন্য নতুন ফিডব্যাক এসেছে।",
            reverse("portal:feedback_detail", args=[feedback.number]),
            email_template="new_feedback", email_subject=f"নতুন প্রজেক্ট ফিডব্যাক {feedback.display_number}: {feedback.topic}",
            context={"feedback": feedback},
        )
    return len(new)


@transaction.atomic
def publish_feedback(feedback: Feedback) -> int:
    if feedback.status != ContentStatus.PUBLISHED:
        feedback.status = ContentStatus.PUBLISHED
        feedback.published_at = feedback.published_at or timezone.now()
        feedback.save(update_fields=["status", "published_at", "updated_at"])
    if feedback.test_id and not feedback.test.is_published:
        test = feedback.test
        test.status = ContentStatus.PUBLISHED
        test.published_at = test.published_at or timezone.now()
        test.save(update_fields=["status", "published_at", "updated_at"])
    return add_recipients(feedback, project_audience(feedback.project, feedback.team))


def sync_member_feedback(user, project, team=None) -> int:
    from django.db.models import Q

    qs = Feedback.objects.filter(project=project, status=ContentStatus.PUBLISHED)
    qs = qs.filter(Q(team__isnull=True) | Q(team=team)) if team else qs.filter(team__isnull=True)
    count = 0
    for fb in qs:
        count += add_recipients(fb, [user], notify_users=False)
    return count


def mark_opened(recipient: FeedbackRecipient, *, has_video: bool) -> FeedbackRecipient:
    now = timezone.now()
    changed = []
    if not recipient.first_viewed_at:
        recipient.first_viewed_at = now
        changed.append("first_viewed_at")
    if not has_video and not recipient.watched_at:
        recipient.watched_at = now  # nothing to watch: opening counts as seen
        recipient.percent = 100
        changed += ["watched_at", "percent"]
    if changed:
        recipient.save(update_fields=changed)
    return recipient


def record_feedback_heartbeat(recipient: FeedbackRecipient, *, duration, ranges, position) -> FeedbackRecipient:
    now = timezone.now()
    result = apply_heartbeat(
        stored_ranges=recipient.watched_ranges, duration=duration, reported_ranges=ranges, position=position,
        last_heartbeat_at=recipient.last_heartbeat_at, now=now, threshold_percent=settings.VIDEO_COMPLETION_THRESHOLD,
        first_viewed_at=recipient.first_viewed_at,
    )
    recipient.watched_ranges = [list(r) for r in result.ranges]
    recipient.watched_seconds = result.watched_seconds
    recipient.percent = max(recipient.percent, result.percent)
    recipient.last_position_sec = result.position
    recipient.last_heartbeat_at = now
    recipient.first_viewed_at = recipient.first_viewed_at or now
    if result.completed and not recipient.watched_at:
        recipient.watched_at = now
    recipient.save()
    return recipient
