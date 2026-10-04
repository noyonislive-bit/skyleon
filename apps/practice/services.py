import math

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.permissions import can_manage_content_for, scoped_project_ids
from apps.core.choices import ContentStatus

from .models import AttemptPhase, AttemptStatus, PracticeAttempt, PracticeTask
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
    """The attempt the workspace edits. Weekly review: the employee's single own-work attempt."""
    if task.is_review:
        return first_attempt(task, user)
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


def score(attempt: PracticeAttempt, user_clips=None) -> None:
    """Fill in metrics / score / passed against the task's reference (or the reviewer's answer). Not saved."""
    task = attempt.task
    lo, hi = task_range(task)
    user_clips = clean_clips(attempt.clips if user_clips is None else user_clips, lo, hi)
    ref = clean_clips(task.reference_clips, lo, hi)
    names = {"ref_en": "reviewer", "ref_bn": "রিভিউয়ারের উত্তরের"} if task.is_review else {}
    metrics = score_attempt(user_clips, ref, lo, hi, task.tolerance_sec, **names)
    attempt.clips = [list(c) for c in user_clips]
    attempt.metrics = metrics
    attempt.score = metrics["score"]
    attempt.passed = metrics["score"] >= task.passing_score


@transaction.atomic
def submit(attempt: PracticeAttempt, clips, time_spent=None) -> PracticeAttempt:
    """Submit (and score, unless it is a weekly review whose answer is not out yet).
    If `clips` is not a list, the last autosaved clips are submitted."""
    task = attempt.task
    lo, hi = task_range(task)
    user_clips = clean_clips(clips if isinstance(clips, list) else attempt.clips, lo, hi)
    if task.scores_now:
        score(attempt, user_clips)
    else:
        attempt.clips = [list(c) for c in user_clips]
        attempt.metrics, attempt.score, attempt.passed = {}, None, None
    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = timezone.now()
    _record_time(attempt, time_spent)
    attempt.save()
    return attempt


# ── Weekly review ───────────────────────────────────────────────────────────
# One "first" attempt per employee holds their own work: it can be edited and re-submitted until the
# reviewer's answer is published, then it is scored and frozen. Corrections are separate attempts.

def first_attempt(task: PracticeTask, user, *, create=True) -> PracticeAttempt | None:
    attempt = PracticeAttempt.objects.filter(task=task, user=user, phase=AttemptPhase.FIRST).order_by("started_at").first()
    if attempt is None and create:
        attempt = PracticeAttempt.objects.create(task=task, user=user, phase=AttemptPhase.FIRST)
    return attempt


def own_work_open(task: PracticeTask, attempt: PracticeAttempt | None) -> bool:
    """The employee's own work can still be edited: always before the answer, afterwards only if never submitted."""
    return not task.answer_published or attempt is None or attempt.status != AttemptStatus.SUBMITTED


def corrections(task: PracticeTask, user):
    return PracticeAttempt.objects.filter(task=task, user=user, phase=AttemptPhase.CORRECTION, status=AttemptStatus.SUBMITTED).order_by("submitted_at")


def correction_draft(task: PracticeTask, user) -> PracticeAttempt:
    """The correction being edited — starts from the latest correction, or from the employee's own work."""
    draft = PracticeAttempt.objects.filter(task=task, user=user, phase=AttemptPhase.CORRECTION, status=AttemptStatus.DRAFT).order_by("-started_at").first()
    if draft:
        return draft
    base = corrections(task, user).last() or first_attempt(task, user, create=False)
    return PracticeAttempt.objects.create(task=task, user=user, phase=AttemptPhase.CORRECTION, clips=list(base.clips) if base else [])


@transaction.atomic
def publish_answer(task: PracticeTask, by) -> int:
    """Release the reviewer's answer: score every submitted own-work attempt and tell the employees."""
    from apps.comms.services import notify

    task.answer_published_at = timezone.now()
    task.answer_by = by
    task.save(update_fields=["answer_published_at", "answer_by", "updated_at"])
    scored = rescore(task)
    submitted = set(PracticeAttempt.objects.filter(task=task, phase=AttemptPhase.FIRST, status=AttemptStatus.SUBMITTED).values_list("user_id", flat=True))
    link = task.get_absolute_url()
    audience = list(audience_for(task))
    notify([u for u in audience if u.pk in submitted], "training", f"রিভিউয়ারের উত্তর প্রকাশিত: {task.title}",
           "আপনার কাজ রিভিউয়ারের উত্তরের সাথে কতটা মিলেছে দেখুন, তারপর নিজের কাজ ঠিক করুন।", link)
    notify([u for u in audience if u.pk not in submitted], "training", f"রিভিউয়ারের উত্তর প্রকাশিত: {task.title}",
           "আগে নিজে ভিডিওটা ক্লিপ করে জমা দিন — তারপর রিভিউয়ারের উত্তরের সাথে মিলিয়ে দেখতে পারবেন।", link)
    return scored


def unpublish_answer(task: PracticeTask) -> None:
    task.answer_published_at = None
    task.save(update_fields=["answer_published_at", "updated_at"])


def rescore(task: PracticeTask) -> int:
    """Score all submitted attempts again (after the answer is published or changed)."""
    n = 0
    for attempt in PracticeAttempt.objects.filter(task=task, status=AttemptStatus.SUBMITTED).select_related("task"):
        score(attempt)
        attempt.save(update_fields=["clips", "metrics", "score", "passed", "updated_at"])
        n += 1
    return n


def audience_for(task: PracticeTask):
    """Active employees who can see the task."""
    from apps.accounts.models import Role, User, UserStatus

    qs = User.objects.filter(role=Role.EMPLOYEE, status=UserStatus.ACTIVE)
    if task.project_id:
        qs = qs.filter(memberships__project_id=task.project_id)
    return qs.distinct()


def announce_review(task: PracticeTask) -> None:
    from apps.comms.services import notify

    due = f" — জমা দেওয়ার শেষ সময় {timezone.localtime(task.due_at):%d/%m, %I:%M %p}" if task.due_at else ""
    notify(list(audience_for(task)), "training", f"এই সপ্তাহের রিভিউ ভিডিও: {task.title}",
           "ভিডিওটা নিজে ক্লিপ করে জমা দিন" + due + "। পরে রিভিউয়ারের উত্তরের সাথে মিলিয়ে দেখতে পারবেন।", task.get_absolute_url())


def review_state(task: PracticeTask, user) -> dict:
    """What the employee should do next on a weekly review task."""
    first = first_attempt(task, user, create=False)
    corr = list(corrections(task, user)) if task.answer_published else []
    submitted = bool(first and first.status == AttemptStatus.SUBMITTED)
    if not submitted:
        state = "todo"
    elif not task.answer_published:
        state = "waiting"
    else:
        state = "corrected" if corr else "answer"
    best = max((c.score for c in corr if c.score is not None), default=None)
    return {
        "state": state, "first": first, "submitted": submitted, "corrections": corr, "best_correction": best,
        "first_score": first.score if submitted and task.answer_published else None,
        "late": bool(submitted and task.due_at and first.submitted_at and first.submitted_at > task.due_at),
        "overdue": bool(not submitted and task.due_at and timezone.now() > task.due_at),
        "draft": bool(first and first.clips and not submitted),
    }


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
