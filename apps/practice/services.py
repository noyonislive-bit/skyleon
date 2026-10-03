from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.permissions import scoped_project_ids
from apps.core.choices import ContentStatus

from .models import AttemptStatus, PracticeAttempt, PracticeTask
from .scoring import clean_clips, score_attempt


def visible_tasks(user):
    """Published practice tasks for the user's projects plus company-wide ones."""
    project_ids = list(user.memberships.values_list("project_id", flat=True))
    return PracticeTask.objects.filter(status=ContentStatus.PUBLISHED).filter(
        Q(project__isnull=True) | Q(project_id__in=project_ids)
    ).select_related("project", "video", "video__thumbnail")


def manageable_tasks(user):
    ids = scoped_project_ids(user)
    qs = PracticeTask.objects.select_related("project", "video")
    if ids is None:
        return qs
    return qs.filter(Q(project__isnull=True) | Q(project_id__in=ids))


def task_range(task: PracticeTask) -> tuple[float, float]:
    lo, hi = task.effective_range()
    if hi is None or hi <= lo:
        hi = lo + 60.0
    return lo, hi


def get_draft(task: PracticeTask, user) -> PracticeAttempt:
    draft = PracticeAttempt.objects.filter(task=task, user=user, status=AttemptStatus.DRAFT).order_by("-started_at").first()
    return draft or PracticeAttempt.objects.create(task=task, user=user)


def save_draft(attempt: PracticeAttempt, clips, time_spent: int | None = None) -> PracticeAttempt:
    lo, hi = task_range(attempt.task)
    attempt.clips = [list(c) for c in clean_clips(clips, lo, hi)]
    if time_spent is not None:
        attempt.time_spent_sec = max(attempt.time_spent_sec, min(int(time_spent), 24 * 3600))
    attempt.save(update_fields=["clips", "time_spent_sec", "updated_at"])
    return attempt


@transaction.atomic
def submit(attempt: PracticeAttempt, clips, time_spent: int | None = None) -> PracticeAttempt:
    task = attempt.task
    lo, hi = task_range(task)
    user_clips = clean_clips(clips, lo, hi)
    ref = clean_clips(task.reference_clips, lo, hi)
    metrics = score_attempt(user_clips, ref, lo, hi, task.tolerance_sec)
    attempt.clips = [list(c) for c in user_clips]
    attempt.metrics = metrics
    attempt.score = metrics["score"]
    attempt.passed = metrics["score"] >= task.passing_score
    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = timezone.now()
    if time_spent is not None:
        attempt.time_spent_sec = max(attempt.time_spent_sec, min(int(time_spent), 24 * 3600))
    attempt.save()
    return attempt


def neighbours(task: PracticeTask, tasks) -> tuple[PracticeTask | None, PracticeTask | None]:
    tasks = list(tasks)
    ids = [t.pk for t in tasks]
    if task.pk not in ids:
        return None, None
    i = ids.index(task.pk)
    return (tasks[i - 1] if i > 0 else None), (tasks[i + 1] if i + 1 < len(tasks) else None)


def user_summary(user, tasks):
    """{task_id: {"best": score, "attempts": n, "passed": bool, "draft": bool}}"""
    out = {t.pk: {"best": None, "attempts": 0, "passed": False, "draft": False} for t in tasks}
    for a in PracticeAttempt.objects.filter(user=user, task__in=tasks).only("task_id", "status", "score", "passed"):
        row = out.get(a.task_id)
        if row is None:
            continue
        if a.status == AttemptStatus.SUBMITTED:
            row["attempts"] += 1
            if a.score is not None and (row["best"] is None or a.score > row["best"]):
                row["best"] = a.score
            row["passed"] = row["passed"] or bool(a.passed)
        elif a.clips:
            row["draft"] = True
    return out
