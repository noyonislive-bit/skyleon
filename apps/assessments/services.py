"""Test assignment, attempts and automatic scoring."""

import random
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from apps.comms.models import NotificationType
from apps.comms.services import notify
from apps.core.audience import project_audience
from apps.core.choices import ContentStatus

from .models import Question, QuestionType, Test, TestAssignment, TestAttempt


class AttemptError(Exception):
    pass


# ── Scoring (pure) ──────────────────────────────────────────────────────────

def grade(questions, selections: dict) -> dict:
    """
    questions: iterable of Question with prefetched options
    selections: {question_id(str|int): [option_id, …]}
    All-or-nothing per question: the selected set must equal the correct set.
    """
    answers, earned, total_points = [], 0, 0
    for q in questions:
        correct_ids = {o.pk for o in q.options.all() if o.is_correct}
        raw = selections.get(str(q.pk), selections.get(q.pk, [])) or []
        valid_ids = {o.pk for o in q.options.all()}
        chosen = set()
        for v in raw:
            try:
                oid = int(v)
            except (TypeError, ValueError):
                continue
            if oid in valid_ids:
                chosen.add(oid)
        if q.qtype in (QuestionType.SINGLE_CHOICE, QuestionType.TRUE_FALSE) and len(chosen) > 1:
            chosen = set()  # invalid submission for single-answer question
        ok = bool(chosen) and chosen == correct_ids
        total_points += q.points
        if ok:
            earned += q.points
        answers.append({"question": q.pk, "selected": sorted(chosen), "correct": ok, "points": q.points if ok else 0})
    score = round(earned / total_points * 100, 2) if total_points else 0.0
    return {"answers": answers, "earned": earned, "total": total_points, "score": score}


# ── Assignment ──────────────────────────────────────────────────────────────

def assign_test(test: Test, users, *, assigned_by=None, due_at=None, notify_users=True) -> int:
    users = list(users)
    existing = set(TestAssignment.objects.filter(test=test, user__in=users).values_list("user_id", flat=True))
    new = [u for u in users if u.pk not in existing]
    TestAssignment.objects.bulk_create(
        [TestAssignment(test=test, user=u, assigned_by=assigned_by, due_at=due_at) for u in new], ignore_conflicts=True
    )
    if notify_users and new:
        notify(
            new, NotificationType.TEST, f"নতুন টেস্ট: {test.title}", "আপনার জন্য একটি নতুন টেস্ট দেওয়া হয়েছে।",
            reverse("portal:test_detail", args=[test.pk]), email_template="new_test",
            email_subject=f"নতুন টেস্ট দিতে হবে: {test.title}", context={"test": test},
        )
    return len(new)


@transaction.atomic
def publish_test(test: Test, *, assign=True, assigned_by=None) -> int:
    if test.status != ContentStatus.PUBLISHED:
        test.status = ContentStatus.PUBLISHED
        test.published_at = test.published_at or timezone.now()
        test.save(update_fields=["status", "published_at", "updated_at"])
    linked_feedback = getattr(test, "feedback", None)  # reverse one-to-one; None when not linked
    if assign and linked_feedback is None and test.project_id:
        return assign_test(test, project_audience(test.project), assigned_by=assigned_by)
    return 0


def sync_member_tests(user, project) -> int:
    count = 0
    for t in Test.objects.filter(project=project, status=ContentStatus.PUBLISHED, feedback__isnull=True):
        count += assign_test(t, [user], notify_users=False)
    return count


# ── Status per user ─────────────────────────────────────────────────────────

@dataclass
class TestState:
    status: str  # pending | in_progress | passed | review | locked
    attempts_used: int
    attempts_left: int | None
    best_score: float | None
    last_attempt: TestAttempt | None
    open_attempt: TestAttempt | None
    attempt_limit: int | None = None  # the test's limit + attempts granted to this person (None = unlimited)
    extra_attempts: int = 0

    @property
    def can_attempt(self):
        return self.status != "passed" and (self.attempts_left is None or self.attempts_left > 0)


def extra_attempts_map(user, test_ids) -> dict:
    """{test_id: extra attempts granted to the user} — feed into test_state(extra_attempts=…) for lists."""
    rows = TestAssignment.objects.filter(user=user, test_id__in=list(test_ids), extra_attempts__gt=0)
    return dict(rows.values_list("test_id", "extra_attempts"))


def test_state(user, test: Test, attempts=None, extra_attempts=None) -> TestState:
    """
    The user's status on a test. `attempts` (newest first) and `extra_attempts` (granted on top of the
    test's attempt limit, see TestAssignment.extra_attempts) are looked up when not given.
    """
    if attempts is None:
        attempts = list(TestAttempt.objects.filter(test=test, user=user).order_by("-attempt_number"))
    submitted = [a for a in attempts if a.submitted_at]
    open_attempt = next((a for a in attempts if not a.submitted_at), None)
    used = len(submitted)
    limit, extra = test.attempt_limit, 0
    if limit is not None:
        if extra_attempts is None:
            extra_attempts = extra_attempts_map(user, [test.pk]).get(test.pk, 0)
        extra = extra_attempts or 0
        limit += extra
    left = None if limit is None else max(0, limit - used)
    best = max((a.score for a in submitted if a.score is not None), default=None)
    if any(a.passed for a in submitted):
        status = "passed"
    elif open_attempt:
        status = "in_progress"
    elif submitted:
        status = "review" if left != 0 else "locked"
    else:
        status = "pending"
    return TestState(status, used, left, best, submitted[0] if submitted else None, open_attempt, limit, extra)


# ── Staff adjustments (admin panel) ─────────────────────────────────────────

@transaction.atomic
def grant_extra_attempt(test: Test, user, *, by=None, count: int = 1) -> TestAssignment:
    """Allow `user` `count` more attempt(s) than the test's limit. Creates the assignment row if needed."""
    assignment, _ = TestAssignment.objects.select_for_update().get_or_create(
        test=test, user=user, defaults={"assigned_by": by}
    )
    assignment.extra_attempts = min(assignment.extra_attempts + count, 999)
    assignment.save(update_fields=["extra_attempts"])
    return assignment


@transaction.atomic
def reset_attempts(test: Test, user) -> int:
    """Delete all of the user's attempts at the test (and any granted extra attempts): they start again from attempt 1."""
    deleted, _ = TestAttempt.objects.filter(test=test, user=user).delete()
    TestAssignment.objects.filter(test=test, user=user).update(extra_attempts=0)
    return deleted


# ── Attempts ────────────────────────────────────────────────────────────────

# Answers that arrive later than this after the time limit are not accepted (network / clock slack).
DEADLINE_GRACE_SECONDS = 120


def is_past_deadline(attempt: TestAttempt, when=None) -> bool:
    deadline = attempt_deadline(attempt)
    return bool(deadline and (when or timezone.now()) > deadline + timezone.timedelta(seconds=DEADLINE_GRACE_SECONDS))


def attempt_deadline(attempt: TestAttempt):
    if not attempt.test.time_limit_min:
        return None
    return attempt.started_at + timezone.timedelta(minutes=attempt.test.time_limit_min)


@transaction.atomic
def start_attempt(user, test: Test) -> TestAttempt:
    if not test.is_published:
        raise AttemptError("This test is not available.")
    state = test_state(user, test)
    if state.open_attempt:
        return state.open_attempt
    if state.status == "passed":
        raise AttemptError("You have already passed this test.")
    if not state.can_attempt:
        raise AttemptError("You have used all attempts for this test.")
    question_ids = list(test.questions.order_by("order", "pk").values_list("pk", flat=True))
    if not question_ids:
        raise AttemptError("This test has no questions yet.")
    if test.shuffle_questions:
        random.shuffle(question_ids)
    number = (TestAttempt.objects.filter(test=test, user=user).aggregate(m=Max("attempt_number"))["m"] or 0) + 1
    return TestAttempt.objects.create(test=test, user=user, attempt_number=number, data={"order": question_ids})


def attempt_questions(attempt: TestAttempt):
    order = attempt.data.get("order") or []
    qs = {q.pk: q for q in Question.objects.filter(test=attempt.test).prefetch_related("options").select_related("media")}
    ordered = [qs[i] for i in order if i in qs]
    ordered += [q for pk, q in qs.items() if pk not in order]
    return ordered


@transaction.atomic
def submit_attempt(attempt: TestAttempt, selections: dict) -> TestAttempt:
    attempt = TestAttempt.objects.select_for_update().select_related("test").get(pk=attempt.pk)
    if attempt.submitted_at:
        return attempt
    now = timezone.now()
    late = is_past_deadline(attempt, now)
    if late:  # the time limit is enforced here, not only in the browser: late answers don't count
        selections = {}
    result = grade(attempt_questions(attempt), selections)
    attempt.submitted_at = now
    attempt.score = result["score"]
    attempt.points_earned = result["earned"]
    attempt.points_total = result["total"]
    attempt.passed = result["score"] >= attempt.test.passing_score
    attempt.data = {**attempt.data, "answers": result["answers"], "late": late}
    attempt.save()
    return attempt
