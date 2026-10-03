"""Tutorial publishing / assignment, progress heartbeats and onboarding status."""

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.comms.models import NotificationType
from apps.comms.services import notify
from apps.core.audience import project_audience
from apps.core.choices import ContentStatus, ProgressStatus

from .models import OnboardingCompletion, OnboardingStep, OnboardingStepType, Tutorial, TutorialProgress
from .progress import apply_heartbeat


# ── Assignment ──────────────────────────────────────────────────────────────

def assign_tutorial(tutorial: Tutorial, users, *, due_at=None, notify_users=True) -> int:
    """Create (or upgrade to assigned) progress rows. Returns number of newly assigned users."""
    users = list(users)
    if not users:
        return 0
    existing = {
        p.user_id: p for p in TutorialProgress.objects.filter(tutorial=tutorial, user__in=users)
    }
    new_rows, upgraded, newly = [], [], []
    for u in users:
        row = existing.get(u.pk)
        if row is None:
            new_rows.append(TutorialProgress(tutorial=tutorial, user=u, assigned=True, due_at=due_at))
            newly.append(u)
        elif not row.assigned:
            row.assigned = True
            row.due_at = due_at or row.due_at
            upgraded.append(row)
            newly.append(u)
    TutorialProgress.objects.bulk_create(new_rows, ignore_conflicts=True)
    if upgraded:
        TutorialProgress.objects.bulk_update(upgraded, ["assigned", "due_at"])
    if notify_users and newly:
        link = reverse("portal:tutorial_detail", args=[tutorial.pk])
        notify(
            newly, NotificationType.TRAINING, f"New training: {tutorial.title}",
            "You have a new training module." + (" It is required." if tutorial.is_required else ""),
            link, email_template="new_training", email_subject="You have a new training module",
            context={"tutorial": tutorial},
        )
    return len(newly)


@transaction.atomic
def publish_tutorial(tutorial: Tutorial, *, assign=True) -> int:
    if tutorial.status != ContentStatus.PUBLISHED:
        tutorial.status = ContentStatus.PUBLISHED
        tutorial.published_at = tutorial.published_at or timezone.now()
        tutorial.save(update_fields=["status", "published_at", "updated_at"])
    if assign and tutorial.is_required:
        return assign_tutorial(tutorial, project_audience(tutorial.project))
    return 0


def get_or_create_progress(tutorial: Tutorial, user) -> TutorialProgress:
    row, _ = TutorialProgress.objects.get_or_create(tutorial=tutorial, user=user, defaults={"assigned": False})
    return row


def record_tutorial_heartbeat(progress: TutorialProgress, *, duration, ranges, position) -> TutorialProgress:
    now = timezone.now()
    result = apply_heartbeat(
        stored_ranges=progress.watched_ranges,
        duration=duration,
        reported_ranges=ranges,
        position=position,
        last_heartbeat_at=progress.last_heartbeat_at,
        now=now,
        threshold_percent=settings.VIDEO_COMPLETION_THRESHOLD,
        first_viewed_at=progress.first_viewed_at,
    )
    progress.watched_ranges = [list(r) for r in result.ranges]
    progress.watched_seconds = result.watched_seconds
    progress.percent = max(progress.percent, result.percent)
    progress.last_position_sec = result.position
    progress.last_heartbeat_at = now
    progress.last_viewed_at = now
    progress.first_viewed_at = progress.first_viewed_at or now
    if result.completed and progress.status != ProgressStatus.COMPLETED:
        progress.status = ProgressStatus.COMPLETED
        progress.completed_at = now
    elif progress.status == ProgressStatus.NOT_STARTED and result.watched_seconds > 0:
        progress.status = ProgressStatus.IN_PROGRESS
    progress.save()
    return progress


def sync_member_tutorials(user, project) -> int:
    """Assign a project's published required tutorials to a (new) member, without emails."""
    count = 0
    for t in Tutorial.objects.filter(project=project, status=ContentStatus.PUBLISHED, is_required=True):
        count += assign_tutorial(t, [user], notify_users=False)
    return count


def sync_global_tutorials(user) -> int:
    count = 0
    for t in Tutorial.objects.filter(project__isnull=True, status=ContentStatus.PUBLISHED, is_required=True):
        count += assign_tutorial(t, [user], notify_users=False)
    return count


# ── Onboarding ──────────────────────────────────────────────────────────────

def step_rule(step: OnboardingStep) -> str:
    if step.tutorial_id:
        return "tutorial"
    if step.test_id:
        return "test"
    if step.step_type == OnboardingStepType.QUALIFICATION:
        return "qualification"
    return "manual"


def _status_maps(user_ids, steps):
    from apps.assessments.models import TestAttempt
    from apps.projects.models import ProjectMember

    tutorial_ids = {s.tutorial_id for s in steps if s.tutorial_id}
    test_ids = {s.test_id for s in steps if s.test_id}
    project_ids = {s.project_id for s in steps if s.project_id}
    completed_tutorials = {
        (p.user_id, p.tutorial_id): p.completed_at
        for p in TutorialProgress.objects.filter(
            user_id__in=user_ids, tutorial_id__in=tutorial_ids, status=ProgressStatus.COMPLETED
        ).only("user_id", "tutorial_id", "completed_at")
    }
    passed_tests = {}
    for a in TestAttempt.objects.filter(user_id__in=user_ids, test_id__in=test_ids, passed=True).only(
        "user_id", "test_id", "submitted_at"
    ):
        passed_tests.setdefault((a.user_id, a.test_id), a.submitted_at)
    qualified = {
        (m.user_id, m.project_id): m.qualified_at
        for m in ProjectMember.objects.filter(
            user_id__in=user_ids, project_id__in=project_ids, qualified_at__isnull=False
        ).only("user_id", "project_id", "qualified_at")
    }
    manual = {
        (c.user_id, c.step_id): c.completed_at
        for c in OnboardingCompletion.objects.filter(user_id__in=user_ids, step__in=steps)
    }
    return completed_tutorials, passed_tests, qualified, manual


def step_done_at(step, user_id, maps):
    completed_tutorials, passed_tests, qualified, manual = maps
    rule = step_rule(step)
    if rule == "tutorial":
        return completed_tutorials.get((user_id, step.tutorial_id))
    if rule == "test":
        return passed_tests.get((user_id, step.test_id))
    if rule == "qualification":
        return qualified.get((user_id, step.project_id))
    return manual.get((user_id, step.pk))


def onboarding_for_user(user):
    """
    Returns a list of sections, one for company-wide onboarding (if any steps)
    and one per project the user belongs to that has onboarding steps:
      {"project": Project|None, "steps": [{"step", "rule", "done_at", "locked"}], "done": n, "total": n, "percent": p}
    Steps unlock sequentially.
    """
    project_ids = list(user.memberships.values_list("project_id", flat=True))
    steps = list(
        OnboardingStep.objects.filter(project__isnull=True).select_related("tutorial", "test", "guideline")
    ) + list(
        OnboardingStep.objects.filter(project_id__in=project_ids).select_related("project", "tutorial", "test", "guideline")
    )
    if not steps:
        return []
    maps = _status_maps([user.pk], steps)
    sections = {}
    for step in sorted(steps, key=lambda s: (s.project_id or 0, s.order, s.pk)):
        sec = sections.setdefault(step.project_id, {"project": step.project if step.project_id else None, "steps": []})
        sec["steps"].append({"step": step, "rule": step_rule(step), "done_at": step_done_at(step, user.pk, maps)})
    result = []
    for sec in sections.values():
        previous_done = True
        for item in sec["steps"]:
            item["locked"] = not previous_done
            previous_done = previous_done and item["done_at"] is not None
        sec["total"] = len(sec["steps"])
        sec["done"] = sum(1 for i in sec["steps"] if i["done_at"])
        sec["percent"] = round(sec["done"] / sec["total"] * 100) if sec["total"] else 0
        sec["completed"] = sec["done"] == sec["total"]
        result.append(sec)
    return result


def onboarding_matrix(project, users):
    """Admin view: for each user → (done, total, next_step_title) on the project's onboarding."""
    steps = list(OnboardingStep.objects.filter(project=project).order_by("order", "pk"))
    users = list(users)
    if not steps or not users:
        return {u.pk: {"done": 0, "total": len(steps), "next": None, "steps": []} for u in users}
    maps = _status_maps([u.pk for u in users], steps)
    out = {}
    for u in users:
        statuses = [step_done_at(s, u.pk, maps) for s in steps]
        done = sum(1 for d in statuses if d)
        nxt = next((s.title for s, d in zip(steps, statuses) if not d), None)
        out[u.pk] = {"done": done, "total": len(steps), "next": nxt, "steps": list(zip(steps, statuses))}
    return out


def complete_manual_step(step: OnboardingStep, user) -> bool:
    if step_rule(step) != "manual":
        return False
    OnboardingCompletion.objects.get_or_create(step=step, user=user)
    return True
