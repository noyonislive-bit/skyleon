from collections import defaultdict

from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Q
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.decorators import staff_required
from apps.accounts.models import Role, User, UserStatus
from apps.accounts.permissions import has_permission, project_scope
from apps.assessments.models import TestAttempt
from apps.comms.models import Meeting
from apps.core.choices import ContentStatus, ProgressStatus
from apps.feedback.models import Feedback
from apps.projects.models import ProjectMember, ProjectStatus
from apps.training.models import TutorialProgress
from apps.website.models import ApplicationStatus, JobApplication, QuoteRequest

from ..helpers import employee_scope, pct, people_q, staff_projects
from .assessments import pending_assignments
from .feedback import tracking_base


@staff_required
def dashboard(request):
    user = request.user
    now = timezone.now()
    employees = employee_scope(user, User.objects.filter(role=Role.EMPLOYEE))
    active_employees = employees.filter(status=UserStatus.ACTIVE)
    people = employees.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(status=UserStatus.ACTIVE)),
        pending=Count("pk", filter=Q(status=UserStatus.PENDING)),
    )
    projects = staff_projects(user)

    training = project_scope(
        TutorialProgress.objects.filter(
            assigned=True, tutorial__is_required=True, tutorial__status=ContentStatus.PUBLISHED, user__in=active_employees
        ),
        user, field="tutorial__project",
    ).aggregate(total=Count("pk"), done=Count("pk", filter=Q(status=ProgressStatus.COMPLETED)))

    can_content = has_permission(user, "content.manage")
    recipients = {"total": 0, "unseen": 0}
    tests_pending = 0
    if can_content:
        # Same definitions as the pages the tiles link to.
        recipients = tracking_base(user).aggregate(total=Count("pk"), unseen=Count("pk", filter=Q(first_viewed_at__isnull=True)))
        tests_pending = pending_assignments(user).count()

    attempts = project_scope(TestAttempt.objects.filter(submitted_at__isnull=False), user, field="test__project").filter(people_q(user))
    score = attempts.aggregate(avg=Avg("score"), n=Count("pk"), passed=Count("pk", filter=Q(passed=True)))

    tiles = [
        {"label": "Total employees", "value": people["total"], "meta": "All employee accounts", "icon": "users",
         "url": "backoffice:employee_list", "query": "?role=employee", "show": has_permission(user, "employees.view")},
        {"label": "Active employees", "value": people["active"], "meta": f"{pct(people['active'], people['total']) or 0}% of all accounts",
         "icon": "user-check", "url": "backoffice:employee_list", "query": "?status=active&role=employee", "show": has_permission(user, "employees.view")},
        {"label": "New applicants", "value": JobApplication.objects.filter(status=ApplicationStatus.NEW).count()
         if has_permission(user, "applicants.manage") else 0, "meta": "Careers applications to review", "icon": "briefcase",
         "url": "backoffice:applicant_list", "query": "?status=new", "show": has_permission(user, "applicants.manage")},
        {"label": "Pending approvals", "value": people["pending"], "meta": "Signups waiting for approval", "icon": "clock",
         "url": "backoffice:employee_list", "query": "?status=pending&role=employee", "show": has_permission(user, "employees.manage"),
         "tone": "warning" if people["pending"] else ""},
        {"label": "Active projects", "value": projects.filter(status=ProjectStatus.ACTIVE).count(),
         "meta": "Assigned to you" if not user.is_super_admin else "Across the company", "icon": "folder-open",
         "url": "backoffice:project_list", "show": True},
        {"label": "Training completion", "value": f"{pct(training['done'], training['total']) or 0}%", "meter": pct(training["done"], training["total"]) or 0,
         "meta": f"{training['done']} of {training['total']} required videos watched", "icon": "graduation-cap",
         "url": "backoffice:training_progress", "show": has_permission(user, "reports.view")},
        {"label": "Unseen feedback", "value": recipients["unseen"], "meta": f"of {recipients['total']} feedback deliveries",
         "icon": "eye-off", "url": "backoffice:feedback_tracking", "query": "?state=unseen", "show": can_content,
         "tone": "warning" if recipients["unseen"] else ""},
        {"label": "Tests pending", "value": tests_pending, "meta": "Assignments without a pass", "icon": "clipboard-list",
         "url": "backoffice:test_list", "query": "?pending=1", "show": can_content},
        {"label": "Average test score", "value": f"{score['avg']:.0f}%" if score["avg"] is not None else "—",
         "meta": f"{score['n']} submitted attempts · {pct(score['passed'], score['n']) or 0}% passed", "icon": "target",
         "url": "backoffice:reports", "show": has_permission(user, "reports.view")},
    ]
    tiles = [t for t in tiles if t["show"]]

    # Team size per project (employees + staff members), with a per-team breakdown for the tooltip.
    chart_projects = list(
        projects.exclude(status=ProjectStatus.ARCHIVED)
        .annotate(n=Count("members", distinct=True), teams_n=Count("teams", distinct=True))
        .order_by("-n", "name")[:10]
    )
    breakdown = defaultdict(list)
    for row in (
        ProjectMember.objects.filter(project__in=[p.pk for p in chart_projects])
        .values("project_id", "team__name").annotate(n=Count("pk")).order_by("team__name")
    ):
        breakdown[row["project_id"]].append((row["team__name"] or "No team", row["n"]))
    chart_max = max([p.n for p in chart_projects] or [0])
    for p in chart_projects:
        p.breakdown = breakdown.get(p.pk, [])

    ctx = {
        "page_title": f"Good {_daypart(now)}, {user.first_name}",
        "crumbs": [("Dashboard", None)],
        "page_subtitle": "Here's what is happening across " + ("the company" if user.is_super_admin else "your projects") + " today.",
        "tiles": tiles,
        "chart_projects": chart_projects,
        "chart_max": chart_max,
        "can_manage_employees": has_permission(user, "employees.manage"),
    }
    if has_permission(user, "employees.manage"):
        ctx["pending_users"] = list(employees.filter(status=UserStatus.PENDING).order_by("-date_joined")[:5])
    if has_permission(user, "applicants.manage"):
        ctx["applicants"] = list(JobApplication.objects.order_by("-created_at")[:5])
    if has_permission(user, "leads.manage"):
        ctx["quotes"] = list(QuoteRequest.objects.order_by("-created_at")[:5])
    if has_permission(user, "content.manage"):
        ctx["recent_attempts"] = list(attempts.select_related("user", "test").order_by("-submitted_at")[:6])
        ctx["attention"] = list(
            project_scope(Feedback.objects.filter(status=ContentStatus.PUBLISHED), user)
            .select_related("project", "team")
            .annotate(total=Count("recipients"), watched=Count("recipients", filter=Q(recipients__watched_at__isnull=False)))
            .filter(total__gt=0)
            .annotate(rate=ExpressionWrapper(F("watched") * 100.0 / F("total"), output_field=FloatField()))
            .order_by("rate", "-published_at")[:5]
        )
    if has_permission(user, "meetings.manage"):
        ctx["meetings"] = list(
            project_scope(Meeting.objects.filter(starts_at__gte=now - timezone.timedelta(hours=2)), user)
            .select_related("project").annotate(invitee_count=Count("invites")).order_by("starts_at")[:5]
        )
    return render(request, "backoffice/dashboard.html", ctx)


def _daypart(now):
    hour = timezone.localtime(now).hour
    return "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
