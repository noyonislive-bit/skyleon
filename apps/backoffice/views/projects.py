from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code, staff_required
from apps.accounts.models import Role
from apps.accounts.permissions import can_manage_content_for, can_manage_project, has_permission
from apps.assessments.models import Test, TestAttempt, TestKind
from apps.core import audit
from apps.core.choices import ContentStatus, ProgressStatus
from apps.feedback.models import Feedback, FeedbackRecipient
from apps.projects.models import Guideline, Project, ProjectMember, ProjectStatus, Team
from apps.projects.services import add_member
from apps.training.models import OnboardingStep, OnboardingStepType, Tutorial, TutorialProgress
from apps.training.services import onboarding_matrix, step_rule

from ..forms import AddMembersForm, GuidelineForm, MemberUpdateForm, OnboardingStepForm, ProjectForm, TeamForm
from ..helpers import assignable_employees, employee_scope, get_project, pct, staff_projects
from ..stats import training_by_user

TABS = [
    ("overview", "Overview", "backoffice:project_detail"),
    ("members", "Members", "backoffice:project_members"),
    ("teams", "Teams", "backoffice:project_teams"),
    ("guidelines", "Guidelines", "backoffice:project_guidelines"),
    ("onboarding", "Onboarding", "backoffice:project_onboarding"),
    ("content", "Content", "backoffice:project_content"),
]

# Employees read these steps in the portal, so the defaults are in Bangla (docs/BANGLA_STYLE.md).
DEFAULT_STEPS = [
    (OnboardingStepType.WELCOME, "স্বাগতম ও প্রজেক্ট পরিচিতি", "প্রজেক্টটি কী নিয়ে, এর লক্ষ্য কী আর কাজ কীভাবে এগোয় — শুরুতেই জেনে নিন।"),
    (OnboardingStepType.GUIDELINE_VIDEO, "প্রজেক্ট গাইডলাইন ভিডিও", "প্রজেক্টের গাইডলাইন ধাপে ধাপে বুঝিয়ে দেওয়া ভিডিওটি দেখুন।"),
    (OnboardingStepType.TUTORIAL, "অ্যানোটেশন টিউটোরিয়াল", "অ্যানোটেশনের কৌশল ধাপে ধাপে শিখে নিন।"),
    (OnboardingStepType.EXAMPLES, "সঠিক কাজের উদাহরণ", "কাজ শুরুর আগে যেসব কাজ accept হয়েছে, সেই উদাহরণগুলো ভালো করে দেখে নিন।"),
    (OnboardingStepType.COMMON_MISTAKES, "সাধারণ ভুলগুলো", "যেসব কারণে কাজ সবচেয়ে বেশি reject হয়, সেগুলো জেনে নিন আর এড়িয়ে চলুন।"),
    (OnboardingStepType.QA_GUIDELINES, "QA / রিভিউ গাইডলাইন", "রিভিউয়াররা আপনার কাজ কীভাবে যাচাই করে স্কোর দেন, তা বুঝে নিন।"),
    (OnboardingStepType.TEST, "ট্রেনিং টেস্ট", "প্রজেক্টের ট্রেনিং টেস্টে পাস করুন।"),
    (OnboardingStepType.QUALIFICATION, "চূড়ান্ত কোয়ালিফিকেশন", "আপনার প্রজেক্ট ম্যানেজার আপনার কাজের একটি নমুনা দেখে আপনাকে কোয়ালিফাই করবেন।"),
]


def _visible_people(user, people):
    """Ids of the given accounts whose employee page the viewer may open (staff members are out of a PM's scope)."""
    if not has_permission(user, "employees.view"):
        return set()
    return set(employee_scope(user).filter(pk__in=[p.pk for p in people]).values_list("pk", flat=True))


def _can_edit_project(user, project):
    return has_permission(user, "projects.manage") and can_manage_project(user, project)


def _ctx(request, project, tab, **extra):
    user = request.user
    counts = {
        "members": project.members.count(),
        "teams": project.teams.count(),
        "guidelines": project.guidelines.count(),
        "onboarding": project.onboarding_steps.count(),
    }
    tabs = [{"key": k, "label": label, "url": reverse(name, args=[project.pk]), "count": counts.get(k)} for k, label, name in TABS]
    return {
        "page_title": None,
        "crumbs": [("Projects", reverse("backoffice:project_list")), (project.code, reverse("backoffice:project_detail", args=[project.pk]))]
        + ([(dict((k, lbl) for k, lbl, _ in TABS)[tab], None)] if tab != "overview" else []),
        "project": project,
        "tab": tab,
        "tabs": tabs,
        "can_edit": _can_edit_project(user, project),
        "can_content": can_manage_content_for(user, project),
        "can_delete_project": has_permission(user, "projects.create") and project.status == ProjectStatus.ARCHIVED,
        **extra,
    }


# ── List / create / edit ────────────────────────────────────────────────────

@staff_required
def project_list(request):
    user = request.user
    qs = staff_projects(user).select_related("organization")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    view = "list" if request.GET.get("view") == "list" else "cards"
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(client_name__icontains=q))
    if status in ProjectStatus.values:
        qs = qs.filter(status=status)
    elif not status:
        qs = qs.exclude(status=ProjectStatus.ARCHIVED)
    projects = list(qs.annotate(
        member_count=Count("members", filter=Q(members__user__role=Role.EMPLOYEE), distinct=True),
        staff_count=Count("members", filter=~Q(members__user__role=Role.EMPLOYEE), distinct=True),
        team_count=Count("teams", distinct=True),
    ).order_by("status", "name"))
    ids = [p.pk for p in projects]
    tutorials = dict(Tutorial.objects.filter(project_id__in=ids).values_list("project_id").annotate(n=Count("pk")))
    feedback = dict(Feedback.objects.filter(project_id__in=ids).values_list("project_id").annotate(n=Count("pk")))
    tests = dict(Test.objects.filter(project_id__in=ids).values_list("project_id").annotate(n=Count("pk")))
    steps = dict(OnboardingStep.objects.filter(project_id__in=ids).values_list("project_id").annotate(n=Count("pk")))
    progress = {
        r["tutorial__project_id"]: pct(r["done"], r["total"])
        for r in TutorialProgress.objects.filter(
            tutorial__project_id__in=ids, assigned=True, tutorial__is_required=True, tutorial__status=ContentStatus.PUBLISHED
        ).values("tutorial__project_id").annotate(total=Count("pk"), done=Count("pk", filter=Q(status=ProgressStatus.COMPLETED)))
    }
    for p in projects:
        p.tutorial_count = tutorials.get(p.pk, 0)
        p.feedback_count = feedback.get(p.pk, 0)
        p.test_count = tests.get(p.pk, 0)
        p.step_count = steps.get(p.pk, 0)
        p.training_pct = progress.get(p.pk)
    return render(request, "backoffice/projects/list.html", {
        "page_title": "Projects",
        "page_subtitle": "Client projects, their teams, guidelines, onboarding and training content.",
        "crumbs": [("Projects", None)],
        "projects": projects,
        "statuses": ProjectStatus.choices,
        "filters": {"q": q, "status": status, "view": view},
        "can_create": has_permission(user, "projects.create"),
    })


@permission_required_code("projects.create")
def project_create(request):
    form = ProjectForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        project = form.save()
        audit.log(request, "project.create", project, code=project.code)
        messages.success(request, f"Project {project.code} created. Next: add members and set up onboarding.")
        return redirect("backoffice:project_members", pk=project.pk)
    return render(request, "backoffice/projects/form.html", {
        "page_title": "New project",
        "crumbs": [("Projects", reverse("backoffice:project_list")), ("New project", None)],
        "form": form,
    })


@permission_required_code("projects.manage")
def project_edit(request, pk):
    project = get_project(request, pk, manage=True)
    form = ProjectForm(request.POST or None, instance=project, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request, "project.edit", project, fields=list(form.changed_data))
        messages.success(request, "Project updated.")
        return redirect("backoffice:project_detail", pk=project.pk)
    return render(request, "backoffice/projects/form.html", {
        "page_title": f"Edit {project.code}",
        "crumbs": [("Projects", reverse("backoffice:project_list")), (project.code, reverse("backoffice:project_detail", args=[project.pk])), ("Edit", None)],
        "form": form,
        "project": project,
    })


def _named(qs, label, plural, field="title", limit=5):
    """'3 tutorials: A, B, C' — what a project deletion takes with it (None when there is nothing)."""
    names = list(qs.values_list(field, flat=True)[: limit + 1])
    if not names:
        return None
    total = qs.count() if len(names) > limit else len(names)
    shown = ", ".join(f"“{n}”" for n in names[:limit]) + (f" and {total - limit} more" if total > limit else "")
    return f"{total} {label if total == 1 else plural}: {shown}"


def _counted(n, label, plural):
    return f"{n} {label if n == 1 else plural}" if n else None


def project_deletion_summary(project):
    from apps.comms.models import Announcement, Meeting

    practice = getattr(project, "practice_tasks", None)  # optional apps
    guides = getattr(project, "guides", None)
    lines = [
        _counted(project.members.count(), "project membership", "project memberships"),
        _named(project.teams.all(), "team", "teams", field="name"),
        _named(project.guidelines.all(), "guideline", "guidelines"),
        _counted(project.onboarding_steps.count(), "onboarding step", "onboarding steps"),
        _named(project.tutorials.all(), "tutorial", "tutorials"),
        _counted(TutorialProgress.objects.filter(tutorial__project=project).count(), "tutorial progress record",
                 "tutorial progress records"),
        _named(project.tests.all(), "test", "tests"),
        _counted(TestAttempt.objects.filter(test__project=project).count(), "test attempt", "test attempts"),
        _named(project.feedback.all(), "feedback item", "feedback items", field="topic"),
        _counted(FeedbackRecipient.objects.filter(feedback__project=project).count(), "feedback delivery", "feedback deliveries"),
        _named(practice.all(), "practice task", "practice tasks") if practice is not None else None,
        _named(guides.all(), "work guide", "work guides") if guides is not None else None,
        _named(Announcement.objects.filter(project=project), "announcement", "announcements"),
        _named(Meeting.objects.filter(project=project), "meeting", "meetings"),
    ]
    return [line for line in lines if line]


@permission_required_code("projects.create")
def project_delete(request, pk):
    """Super admins permanently delete an ARCHIVED project and everything that belongs to it."""
    from apps.comms.models import Meeting

    project = get_object_or_404(Project, pk=pk)
    problem = None
    if project.status != ProjectStatus.ARCHIVED:
        problem = ("Only archived projects can be deleted. Edit the project and set its status to Archived first — "
                   "an archived project is hidden from employees and clients but keeps all of its data.")
    if request.method == "POST":
        if problem:
            messages.error(request, problem)
            return redirect("backoffice:project_detail", pk=project.pk)
        code, name = project.code, project.name
        with transaction.atomic():
            audit.log(request, "project.delete", project, code=code, name=name, deleted=project_deletion_summary(project))
            Meeting.objects.filter(project=project).delete()  # would otherwise become company-wide meetings
            project.delete()
        messages.success(request, f"Project {code} · {name} and all of its content were deleted.")
        return redirect("backoffice:project_list")
    return render(request, "backoffice/confirm_delete.html", {
        "page_title": f"Delete project {project.code}?",
        "page_subtitle": f"{project.name} · {project.get_status_display()}",
        "crumbs": [("Projects", reverse("backoffice:project_list")),
                   (project.code, reverse("backoffice:project_detail", args=[project.pk])), ("Delete", None)],
        "problem": problem,
        "warning": f"This permanently deletes the project {project.code} · {project.name} with all of its content and "
                   "everyone's progress on it. This cannot be undone.",
        "deleted": project_deletion_summary(project),
        "kept": ["Employee and client accounts (they are only removed from the project).",
                 "Company-wide content, and uploaded video / document files in the media storage.",
                 "The audit log."],
        "confirm_label": "Delete project permanently",
        "cancel_url": reverse("backoffice:project_detail", args=[project.pk]),
    })


# ── Detail tabs ─────────────────────────────────────────────────────────────

@staff_required
def project_detail(request, pk):
    project = get_project(request, pk)
    members = list(project.members.select_related("user", "team"))
    employees = [m.user for m in members if m.user.role == Role.EMPLOYEE]
    matrix = onboarding_matrix(project, employees)
    onboarded = sum(1 for u in employees if matrix[u.pk]["total"] and matrix[u.pk]["done"] == matrix[u.pk]["total"])
    onboarding_avg = (
        round(sum(matrix[u.pk]["done"] / matrix[u.pk]["total"] * 100 for u in employees) / len(employees))
        if employees and matrix and any(matrix[u.pk]["total"] for u in employees) else None
    )
    training = TutorialProgress.objects.filter(
        tutorial__project=project, assigned=True, tutorial__is_required=True, tutorial__status=ContentStatus.PUBLISHED,
    ).aggregate(total=Count("pk"), done=Count("pk", filter=Q(status=ProgressStatus.COMPLETED)))
    fb = FeedbackRecipient.objects.filter(feedback__project=project, feedback__status=ContentStatus.PUBLISHED).aggregate(
        total=Count("pk"), watched=Count("pk", filter=Q(watched_at__isnull=False)), seen=Count("pk", filter=Q(first_viewed_at__isnull=False)))
    attempts = TestAttempt.objects.filter(test__project=project, submitted_at__isnull=False).aggregate(
        users=Count("user", distinct=True), passed=Count("user", filter=Q(passed=True), distinct=True), n=Count("pk"))
    teams = list(project.teams.select_related("lead").annotate(n=Count("members")))
    stats = [
        {"label": "Members", "value": len(members), "meta": f"{len(employees)} employees · {len(members) - len(employees)} staff", "icon": "users"},
        {"label": "Onboarding", "value": f"{onboarding_avg}%" if onboarding_avg is not None else "—", "meter": onboarding_avg,
         "meta": f"{onboarded} of {len(employees)} fully onboarded" if project.onboarding_steps.exists() else "No onboarding steps yet", "icon": "route"},
        {"label": "Training completion", "value": f"{pct(training['done'], training['total'])}%" if training["total"] else "—",
         "meter": pct(training["done"], training["total"]), "meta": f"{training['done']} of {training['total']} required videos", "icon": "graduation-cap"},
        {"label": "Feedback watch rate", "value": f"{pct(fb['watched'], fb['total'])}%" if fb["total"] else "—",
         "meter": pct(fb["watched"], fb["total"]), "meta": f"{fb['watched']} of {fb['total']} deliveries watched", "icon": "scan-eye"},
        {"label": "Test pass rate", "value": f"{pct(attempts['passed'], attempts['users'])}%" if attempts["users"] else "—",
         "meter": pct(attempts["passed"], attempts["users"]), "meta": f"{attempts['passed']} of {attempts['users']} test takers passed", "icon": "badge-check"},
    ]
    recent_feedback = list(project.feedback.filter(status=ContentStatus.PUBLISHED).annotate(
        total=Count("recipients"), watched=Count("recipients", filter=Q(recipients__watched_at__isnull=False))
    ).order_by("-published_at")[:5])
    staff = [m for m in members if m.user.role != Role.EMPLOYEE]
    return render(request, "backoffice/projects/overview.html", _ctx(
        request, project, "overview", stats=stats, teams=teams, staff=staff, recent_feedback=recent_feedback,
    ))


@staff_required
def project_members(request, pk):
    project = get_project(request, pk)
    user = request.user
    can_edit = _can_edit_project(user, project)
    form = AddMembersForm(request.POST or None, user=user, project=project) if can_edit else None
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if form.is_valid():
            d = form.cleaned_data
            for person in d["users"]:
                add_member(project, person, role=d["role"], team=d["team"])
            audit.log(request, "project.member_add", project, users=[u.pk for u in d["users"]], role=d["role"])
            messages.success(request, f"Added {len(d['users'])} member(s) to {project.name}. Their project training is now assigned.")
            return redirect("backoffice:project_members", pk=project.pk)
        if not request.POST.getlist("users"):
            messages.error(request, "Select at least one person to add.")
        elif form.has_error("users"):
            messages.error(request, "Some of the selected people can't be added — they are already members, not active, "
                                    "or outside the people you manage. Nobody was added.")
        else:
            messages.error(request, "Nobody was added — please correct the errors below.")
    members = list(project.members.select_related("user", "team", "qualified_by").order_by("team__name", "user__name"))
    team_filter = request.GET.get("team", "")
    if team_filter == "none":
        members = [m for m in members if m.team_id is None]
    elif team_filter.isdigit():
        members = [m for m in members if m.team_id == int(team_filter)]
    users = [m.user for m in members]
    visible = _visible_people(user, users)
    matrix = onboarding_matrix(project, users)
    training = training_by_user([u.pk for u in users], only_project=project)
    team_choices = [("", "No team")] + [(t.pk, t.name) for t in project.teams.all()]
    for m in members:
        m.onboarding = matrix.get(m.user_id)
        m.training = training.get(m.user_id)
        m.form = MemberUpdateForm(initial={"role": m.role, "team": m.team_id}, project=project, prefix=f"m{m.pk}")
        m.form.fields["team"].widget.choices = team_choices  # render without one query per row
        m.can_manage = can_edit and (m.user.role == Role.EMPLOYEE or has_permission(user, "staff.manage"))
        m.can_view = m.user_id in visible
    return render(request, "backoffice/projects/members.html", _ctx(
        request, project, "members", members=members, form=form, teams=project.teams.all(), team_filter=team_filter,
    ))


@staff_required
def project_teams(request, pk):
    project = get_project(request, pk)
    can_edit = _can_edit_project(request.user, project)
    form = TeamForm(request.POST or None, project=project) if can_edit else None
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if form.is_valid():
            team = form.save(commit=False)
            team.project = project
            team.save()
            audit.log(request, "team.create", team, project=project.code)
            messages.success(request, f"Team “{team.name}” created.")
            return redirect("backoffice:project_teams", pk=project.pk)
    teams = list(project.teams.select_related("lead").annotate(n=Count("members")))
    lead_choices = TeamForm.lead_choices(project) if teams else None
    for t in teams:
        t.form = TeamForm(instance=t, project=project, prefix=f"t{t.pk}", lead_choices=lead_choices)
    unassigned = project.members.filter(team__isnull=True).count()
    return render(request, "backoffice/projects/teams.html", _ctx(request, project, "teams", teams=teams, form=form, unassigned=unassigned))


@require_POST
@permission_required_code("projects.manage")
def team_update(request, pk):
    team = get_object_or_404(Team.objects.select_related("project"), pk=pk)
    project = get_project(request, team.project_id, manage=True)
    form = TeamForm(request.POST, instance=team, project=project, prefix=f"t{team.pk}")
    if form.is_valid():
        form.save()
        audit.log(request, "team.update", team)
        messages.success(request, f"Team “{team.name}” saved.")
    else:
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("backoffice:project_teams", pk=project.pk)


@require_POST
@permission_required_code("projects.manage")
def team_delete(request, pk):
    team = get_object_or_404(Team.objects.select_related("project"), pk=pk)
    project = get_project(request, team.project_id, manage=True)
    name = team.name
    audit.log(request, "team.delete", team, name=name)
    team.delete()
    messages.success(request, f"Team “{name}” deleted. Its members stay on the project without a team.")
    return redirect("backoffice:project_teams", pk=project.pk)


# ── Guidelines ──────────────────────────────────────────────────────────────

@staff_required
def project_guidelines(request, pk):
    project = get_project(request, pk)
    guidelines = list(project.guidelines.select_related("document").annotate(
        ack_current=Count("acks", filter=Q(acks__version=F("version"))), ack_total=Count("acks"),
    ))
    member_count = project.members.filter(user__role=Role.EMPLOYEE).count()
    return render(request, "backoffice/projects/guidelines.html", _ctx(
        request, project, "guidelines", guidelines=guidelines, member_count=member_count,
    ))


def _guideline_form(request, project, guideline=None):
    form = GuidelineForm(request.POST or None, instance=guideline, user=request.user,
                         initial=None if guideline else {"order": project.guidelines.count() + 1, "version": "1.0"})
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.project = project
        obj.save()
        audit.log(request, "guideline.edit" if guideline else "guideline.create", obj, version=obj.version)
        messages.success(request, "Guideline saved.")
        return redirect("backoffice:project_guidelines", pk=project.pk)
    return render(request, "backoffice/projects/guideline_form.html", _ctx(
        request, project, "guidelines", form=form, guideline=guideline,
        page_title=f"Edit guideline" if guideline else "New guideline",
    ))


@permission_required_code("projects.manage")
def guideline_create(request, pk):
    return _guideline_form(request, get_project(request, pk, manage=True))


@permission_required_code("projects.manage")
def guideline_edit(request, pk):
    guideline = get_object_or_404(Guideline.objects.select_related("project", "document"), pk=pk)
    return _guideline_form(request, get_project(request, guideline.project_id, manage=True), guideline)


@require_POST
@permission_required_code("projects.manage")
def guideline_delete(request, pk):
    guideline = get_object_or_404(Guideline, pk=pk)
    project = get_project(request, guideline.project_id, manage=True)
    audit.log(request, "guideline.delete", guideline, title=guideline.title)
    guideline.delete()
    messages.success(request, "Guideline deleted.")
    return redirect("backoffice:project_guidelines", pk=project.pk)


# ── Onboarding ──────────────────────────────────────────────────────────────

def _step_rows(project, employees):
    """The onboarding steps of a project (or the company-wide ones, project=None) with how many employees completed each."""
    steps = list(OnboardingStep.objects.filter(project=project).select_related("tutorial", "test", "guideline").order_by("order", "pk"))
    matrix = onboarding_matrix(project, employees)
    done_by_step = {s.pk: 0 for s in steps}
    for data in matrix.values():
        for step, done_at in data["steps"]:
            if done_at:
                done_by_step[step.pk] = done_by_step.get(step.pk, 0) + 1
    for s in steps:
        s.rule = step_rule(s)
        s.done_count = done_by_step.get(s.pk, 0)
    return steps


@staff_required
def project_onboarding(request, pk):
    project = get_project(request, pk)
    employees = [m.user for m in project.members.select_related("user").filter(user__role=Role.EMPLOYEE)]
    steps = _step_rows(project, employees)
    form = OnboardingStepForm(project=project) if can_manage_content_for(request.user, project) else None
    return render(request, "backoffice/projects/onboarding.html", _ctx(
        request, project, "onboarding", steps=steps, employee_count=len(employees), form=form,
    ))


def _content_project(request, pk):
    project = get_project(request, pk)
    if not can_manage_content_for(request.user, project):
        raise PermissionDenied
    return project


def _managed_step(request, pk):
    """A step the user may edit: project steps need the project, company-wide steps need company-wide content rights."""
    step = get_object_or_404(OnboardingStep.objects.select_related("project"), pk=pk)
    if step.project_id is None:
        if not can_manage_content_for(request.user, None):
            raise PermissionDenied
        return step, None
    return step, _content_project(request, step.project_id)


def _onboarding_url(project):
    return reverse("backoffice:project_onboarding", args=[project.pk]) if project else reverse("backoffice:company_onboarding")


def _renumber(project):
    for i, step in enumerate(OnboardingStep.objects.filter(project=project).order_by("order", "pk"), start=1):
        if step.order != i:
            OnboardingStep.objects.filter(pk=step.pk).update(order=i)


@permission_required_code("content.manage")
def step_create(request, pk):
    project = _content_project(request, pk)
    form = OnboardingStepForm(request.POST or None, project=project)
    if request.method == "POST" and form.is_valid():
        step = form.save(commit=False)
        step.project = project
        step.order = OnboardingStep.objects.filter(project=project).count() + 1
        step.save()
        audit.log(request, "onboarding.create", step, project=project.code)
        messages.success(request, f"Step “{step.title}” added.")
        return redirect("backoffice:project_onboarding", pk=project.pk)
    return render(request, "backoffice/projects/step_form.html", _ctx(request, project, "onboarding", form=form, page_title="Add onboarding step"))


@permission_required_code("content.manage")
def step_edit(request, pk):
    step, project = _managed_step(request, pk)
    if project is None:
        return company_step_edit(request, pk)
    form = OnboardingStepForm(request.POST or None, instance=step, project=project)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request, "onboarding.edit", step)
        messages.success(request, "Step saved.")
        return redirect("backoffice:project_onboarding", pk=project.pk)
    return render(request, "backoffice/projects/step_form.html", _ctx(request, project, "onboarding", form=form, step=step, page_title="Edit onboarding step"))


@require_POST
@permission_required_code("content.manage")
def step_delete(request, pk):
    step, project = _managed_step(request, pk)
    audit.log(request, "onboarding.delete", step, title=step.title, project=project.code if project else None)
    step.delete()
    _renumber(project)
    messages.success(request, "Step deleted.")
    return redirect(_onboarding_url(project))


@require_POST
@permission_required_code("content.manage")
def step_move(request, pk):
    step, project = _managed_step(request, pk)
    with transaction.atomic():
        steps = list(OnboardingStep.objects.select_for_update().filter(project=project).order_by("order", "pk"))
        idx = next(i for i, s in enumerate(steps) if s.pk == step.pk)
        target = idx - 1 if request.POST.get("direction") == "up" else idx + 1
        if 0 <= target < len(steps):
            steps[idx], steps[target] = steps[target], steps[idx]
            for i, s in enumerate(steps, start=1):
                if s.order != i:
                    OnboardingStep.objects.filter(pk=s.pk).update(order=i)
    return redirect(_onboarding_url(project) + f"#step-{step.pk}")


# ── Company-wide onboarding (steps with project=None — every employee does them) ──

def _company_crumbs(*extra):
    return [("Company onboarding", reverse("backoffice:company_onboarding"))] + list(extra)


@permission_required_code("content.manage")
def company_onboarding(request):
    user = request.user
    employees = list(assignable_employees(user))
    can_edit = can_manage_content_for(user, None)
    return render(request, "backoffice/training/company_onboarding.html", {
        "page_title": "Company onboarding",
        "page_subtitle": "Steps every employee completes, before and next to their project onboarding.",
        "crumbs": [("Company onboarding", None)],
        "steps": _step_rows(None, employees),
        "employee_count": len(employees),
        "can_edit": can_edit,
        "form": OnboardingStepForm(project=None) if can_edit else None,
    })


def _company_step_form(request, step=None):
    if not can_manage_content_for(request.user, None):
        raise PermissionDenied
    form = OnboardingStepForm(request.POST or None, instance=step, project=None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if step is None:
            obj.project = None
            obj.order = OnboardingStep.objects.filter(project__isnull=True).count() + 1
        obj.save()
        audit.log(request, "onboarding.edit" if step else "onboarding.create", obj, project=None)
        messages.success(request, "Step saved." if step else f"Step “{obj.title}” added.")
        return redirect(reverse("backoffice:company_onboarding") + f"#step-{obj.pk}")
    title = "Edit company onboarding step" if step else "Add company onboarding step"
    return render(request, "backoffice/training/company_step_form.html", {
        "page_title": title,
        "page_subtitle": "Employees see the step in Bangla in their portal — write the title and text in Bangla.",
        "crumbs": _company_crumbs(("Edit step" if step else "Add step", None)),
        "form": form,
        "step": step,
    })


@permission_required_code("content.manage")
def company_step_create(request):
    return _company_step_form(request)


@permission_required_code("content.manage")
def company_step_edit(request, pk):
    return _company_step_form(request, get_object_or_404(OnboardingStep, pk=pk, project__isnull=True))


@require_POST
@permission_required_code("content.manage")
def onboarding_template(request, pk):
    project = _content_project(request, pk)
    if OnboardingStep.objects.filter(project=project).exists():
        messages.error(request, "This project already has onboarding steps.")
        return redirect("backoffice:project_onboarding", pk=project.pk)
    test = (Test.objects.filter(project=project, kind__in=[TestKind.ONBOARDING, TestKind.TRAINING])
            .exclude(status=ContentStatus.ARCHIVED).order_by("-kind", "pk").first())
    with transaction.atomic():
        for i, (stype, title, desc) in enumerate(DEFAULT_STEPS, start=1):
            OnboardingStep.objects.create(
                project=project, order=i, step_type=stype, title=title, description=desc,
                test=test if stype == OnboardingStepType.TEST else None,
            )
    audit.log(request, "onboarding.template", project)
    messages.success(request, "The default 8-step onboarding was created. Link tutorials, guidelines and the test to each step.")
    return redirect("backoffice:project_onboarding", pk=project.pk)


# ── Content ─────────────────────────────────────────────────────────────────

@staff_required
def project_content(request, pk):
    project = get_project(request, pk)
    tutorials = list(project.tutorials.select_related("category", "video").annotate(
        assigned=Count("progress", filter=Q(progress__assigned=True)),
        completed=Count("progress", filter=Q(progress__assigned=True, progress__status=ProgressStatus.COMPLETED)),
    ).order_by("-created_at"))
    feedback = list(project.feedback.select_related("team", "test").annotate(
        total=Count("recipients"), watched=Count("recipients", filter=Q(recipients__watched_at__isnull=False)),
    ).order_by("-number"))
    tests = list(project.tests.annotate(
        question_count=Count("questions", distinct=True), assigned=Count("assignments", distinct=True),
    ).order_by("-created_at"))
    return render(request, "backoffice/projects/content.html", _ctx(
        request, project, "content", tutorials=tutorials, feedback=feedback, tests=tests,
    ))
