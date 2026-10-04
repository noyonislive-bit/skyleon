"""
What an employee may see in the portal, computed once per request.

Every portal view is wrapped with ``@portal_view`` which (after the
``employee_required`` permission check) attaches ``request.portal`` — a
``PortalScope`` for the signed-in user. Templates read the sidebar counts from
``request.portal.counts`` (evaluated lazily, once).

Access rules:
  * only PUBLISHED content,
  * of projects the user is a member of, plus company-wide content (project = NULL),
  * feedback only for recipients, meetings only for invitees,
  * staff roles get the same scoped view of their own memberships; clients have no access.
"""

from functools import cached_property, wraps

from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import employee_required
from apps.accounts.permissions import has_permission
from apps.assessments.models import Test, TestAssignment, TestAttempt
from apps.comms.models import Announcement, AnnouncementRead, Notification
from apps.core.choices import ContentStatus, ProgressStatus
from apps.feedback.models import FeedbackRecipient
from apps.projects.models import Guideline, ProjectMember
from apps.training.models import OnboardingStep, Tutorial, TutorialProgress

PUBLISHED = ContentStatus.PUBLISHED


class PortalScope:
    def __init__(self, user):
        self.user = user

    # ── Membership ─────────────────────────────────────────────────────────
    @cached_property
    def memberships(self) -> list[ProjectMember]:
        return list(
            ProjectMember.objects.filter(user=self.user)
            .select_related("project", "team", "qualified_by")
            .order_by("project__name")
        )

    @cached_property
    def project_ids(self) -> list[int]:
        return [m.project_id for m in self.memberships]

    def membership(self, project_id):
        return next((m for m in self.memberships if m.project_id == project_id), None)

    def in_scope(self, field="project", include_global=True) -> Q:
        cond = Q(**{f"{field}_id__in": self.project_ids})
        if include_global:
            cond |= Q(**{f"{field}__isnull": True})
        return cond

    # ── Visible content ────────────────────────────────────────────────────
    def tutorials(self):
        return Tutorial.objects.filter(status=PUBLISHED).filter(self.in_scope())

    def guidelines(self):
        return Guideline.objects.filter(project_id__in=self.project_ids)

    def recipients(self):
        """The user's FeedbackRecipient rows for published feedback of their projects."""
        return FeedbackRecipient.objects.filter(
            user=self.user, feedback__status=PUBLISHED, feedback__project_id__in=self.project_ids
        )

    def tests(self):
        """
        Published tests the user may take:
          * feedback tests → only when the user received that feedback,
          * other tests of the user's projects,
          * company-wide tests assigned to the user,
          * tests linked from an onboarding step the user sees.
        """
        assigned = TestAssignment.objects.filter(user=self.user).values("test_id")
        feedback_tests = self.recipients().filter(feedback__test__isnull=False).values("feedback__test_id")
        onboarding_tests = OnboardingStep.objects.filter(self.in_scope(), test__isnull=False).values("test_id")
        regular = Q(feedback__isnull=True) & (
            Q(project_id__in=self.project_ids) | (Q(project__isnull=True) & Q(pk__in=assigned))
        )
        return Test.objects.filter(status=PUBLISHED).filter(
            regular | Q(pk__in=feedback_tests) | Q(pk__in=onboarding_tests)
        )

    def announcements(self):
        return Announcement.objects.filter(self.in_scope())

    # ── Annotations shared by several views ────────────────────────────────
    def completed_tutorial(self):
        return Exists(
            TutorialProgress.objects.filter(tutorial=OuterRef("pk"), user=self.user, status=ProgressStatus.COMPLETED)
        )

    def announcement_read(self):
        return Exists(AnnouncementRead.objects.filter(announcement=OuterRef("pk"), user=self.user))

    def open_tests(self):
        """Visible tests that still need doing: not passed and with attempts left (incl. extra attempts granted)."""
        user = self.user
        extra = TestAssignment.objects.filter(test=OuterRef("pk"), user=user).values("extra_attempts")[:1]
        return (
            self.tests()
            .annotate(
                passed_n=Count("attempts", filter=Q(attempts__user=user, attempts__passed=True), distinct=True),
                used_n=Count(
                    "attempts", filter=Q(attempts__user=user, attempts__submitted_at__isnull=False), distinct=True
                ),
                extra_n=Coalesce(Subquery(extra), Value(0)),
            )
            .filter(passed_n=0)
            .filter(Q(attempt_limit__isnull=True) | Q(used_n__lt=F("attempt_limit") + F("extra_n")))
        )

    # ── Sidebar / top-bar counts (a handful of cheap COUNT queries) ─────────
    @cached_property
    def counts(self) -> dict:
        user = self.user
        return {
            "training": self.tutorials().filter(is_required=True).exclude(self.completed_tutorial()).count(),
            "feedback": self.recipients().filter(first_viewed_at__isnull=True).count(),
            "tests": self.open_tests().count(),
            "announcements": self.announcements().exclude(self.announcement_read()).count(),
            "notifications": Notification.objects.filter(user=user, read_at__isnull=True).count(),
        }


def portal_view(view):
    """employee_required + attach request.portal."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        request.portal = PortalScope(request.user)
        return view(request, *args, **kwargs)

    return employee_required(wrapper)


def portal_api(view):
    """JSON endpoint: POST only, JSON 403 instead of redirects for users without portal access."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not has_permission(request.user, "portal.access"):
            return JsonResponse({"error": "এই কাজের অনুমতি আপনার নেই।"}, status=403)
        request.portal = PortalScope(request.user)
        return view(request, *args, **kwargs)

    return require_POST(wrapper)


def attempts_by_test(user, test_ids) -> dict:
    """{test_id: [TestAttempt…]} newest first — feed into assessments.services.test_state(attempts=…)."""
    grouped: dict[int, list] = {}
    for a in TestAttempt.objects.filter(user=user, test_id__in=list(test_ids)).order_by("-attempt_number"):
        grouped.setdefault(a.test_id, []).append(a)
    return grouped
