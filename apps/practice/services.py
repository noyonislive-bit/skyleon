import math

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.permissions import can_manage_content_for, scoped_project_ids
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
    """Tasks the staff member may edit: their projects' tasks, plus company-wide ones if they may
    manage company-wide content (super admins, trainers) — never rows whose pages would 404."""
    ids = scoped_project_ids(user)
    qs = PracticeTask.objects.select_related("project", "video")
    if ids is None:
        return qs
    if can_manage_content_for(user, None):
        return qs.filter(Q(project__isnull=True) | Q(project_id__in=ids))
    return qs.filter(project_id__in=ids)


def task_range(task: PracticeTask) -> tuple[float, float]:
    lo, hi = task.effective_range()
    if hi is None or hi <= lo:
        hi = lo + 60.0
    return lo, hi


def get_draft(task: PracticeTask, user) -> PracticeAttempt:
    draft = PracticeAttempt.objects.filter(task=task, user=user, status=AttemptStatus.DRAFT).order_by("-started_at").first()
    return draft or PracticeAttempt.objects.create(task=task, user=user)


MAX_TIME_SPENT = 24 * 3600


def coerce_seconds(value) -> int | None:
    """Client-reported seconds ("timeSpent") → int clamped to 0…MAX_TIME_SPENT, or None if not a finite number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return int(max(0.0, min(number, MAX_TIME_SPENT)))


def _record_time(attempt: PracticeAttempt, time_spent) -> None:
    """
    The tool reports the active time of the current page session (it starts at 0 on every load),
    so the attempt keeps the longest session rather than adding the reports up — repeated autosaves
    of one session would otherwise be counted many times. Time from earlier sessions of the same
    draft is therefore not added (a known under-count, never an over-count).
    """
    seconds = coerce_seconds(time_spent)
    if seconds is not None:
        attempt.time_spent_sec = max(attempt.time_spent_sec or 0, seconds)


def save_draft(attempt: PracticeAttempt, clips, time_spent=None) -> PracticeAttempt:
    """Autosave. `clips` must be a list of [start, end] pairs; anything else leaves the saved clips untouched."""
    lo, hi = task_range(attempt.task)
    if isinstance(clips, list):
        attempt.clips = [list(c) for c in clean_clips(clips, lo, hi)]
    _record_time(attempt, time_spent)
    attempt.save(update_fields=["clips", "time_spent_sec", "updated_at"])
    return attempt


@transaction.atomic
def submit(attempt: PracticeAttempt, clips, time_spent=None) -> PracticeAttempt:
    """Score and submit. If `clips` is not a list, the last autosaved clips are submitted."""
    task = attempt.task
    lo, hi = task_range(task)
    user_clips = clean_clips(clips if isinstance(clips, list) else attempt.clips, lo, hi)
    ref = clean_clips(task.reference_clips, lo, hi)
    metrics = score_attempt(user_clips, ref, lo, hi, task.tolerance_sec)
    attempt.clips = [list(c) for c in user_clips]
    attempt.metrics = metrics
    attempt.score = metrics["score"]
    attempt.passed = metrics["score"] >= task.passing_score
    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = timezone.now()
    _record_time(attempt, time_spent)
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
