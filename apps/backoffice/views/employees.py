from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Prefetch, Q, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.models import Role, User, UserStatus
from apps.accounts.permissions import can_manage_content_for, can_manage_project, has_permission, project_scope
from apps.accounts.services import (
    approve_user,
    change_role,
    create_account,
    password_setup_url,
    reactivate_user,
    suspend_user,
)
from apps.assessments.models import Test, TestAssignment, TestAttempt
from apps.assessments.services import assign_test, test_state
from apps.comms.services import absolute_url, queue_email
from apps.core import audit
from apps.core.choices import ContentStatus
from apps.feedback.models import Feedback, FeedbackRecipient
from apps.feedback.services import add_recipients
from apps.projects.models import MemberRole, Project, ProjectMember, Team
from apps.projects.services import add_member, qualify_member, remove_member
from apps.training.models import Tutorial, TutorialProgress
from apps.training.services import assign_tutorial, onboarding_for_user

from ..forms import (
    AssignFeedbackForm,
    AssignTestForm,
    AssignTutorialForm,
    EmployeeCreateForm,
    EmployeeEditForm,
    MemberUpdateForm,
    MembershipForm,
    RoleForm,
)
from ..helpers import (
    can_manage_employee,
    day_end,
    employee_scope,
    get_employee,
    paginate,
    redirect_back,
    scope_ids,
    staff_projects,
)
from ..stats import training_by_user

TABS = [("overview", "Overview"), ("onboarding", "Onboarding"), ("tutorials", "Tutorials"), ("feedback", "Feedback"), ("tests", "Tests")]


@permission_required_code("employees.view")
def employee_list(request):
    user = request.user
    qs = employee_scope(user)
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    role = request.GET.get("role", "")
    project_id = request.GET.get("project", "")
    if role in Role.values:
        qs = qs.filter(role=role)
    elif user.is_super_admin:
        qs = qs.exclude(role=Role.CLIENT)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(employee_id__icontains=q))
    if status in UserStatus.values:
        qs = qs.filter(status=status)
    projects = staff_projects(user).order_by("name")
    if project_id == "none":
        qs = qs.filter(memberships__isnull=True)
    elif project_id.isdigit() and projects.filter(pk=int(project_id)).exists():
        qs = qs.filter(memberships__project_id=int(project_id))
    ids = scope_ids(user)
    member_qs = ProjectMember.objects.select_related("project", "team")
    if ids is not None:
        member_qs = member_qs.filter(project_id__in=ids)
    pending_first = Case(When(status=UserStatus.PENDING, then=Value(0)), default=Value(1), output_field=IntegerField())
    qs = qs.prefetch_related(Prefetch("memberships", queryset=member_qs)).order_by(pending_first, "name")
    page = paginate(request, qs)
    training = training_by_user([u.pk for u in page], ids)
    for u in page:
        u.training = training.get(u.pk)
    return render(request, "backoffice/employees/list.html", {
        "page_title": "Employees",
        "page_subtitle": "Accounts, approvals, project assignments and training progress.",
        "crumbs": [("Employees", None)],
        "page": page,
        "projects": projects,
        "statuses": UserStatus.choices,
        "roles": [c for c in Role.choices if user.is_super_admin or c[0] == Role.EMPLOYEE],
        "filters": {"q": q, "status": status, "role": role, "project": project_id},
        "can_create": has_permission(user, "employees.manage"),
        "pending_count": employee_scope(user, User.objects.filter(status=UserStatus.PENDING, role=Role.EMPLOYEE)).count(),
    })


@permission_required_code("employees.manage")
def employee_create(request):
    form = EmployeeCreateForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        account = create_account(
            email=d["email"], name=d["name"], role=d["role"], invited_by=request.user, send_invite=d["send_invite"],
            phone=d.get("phone", ""), location=d.get("location", ""), title=d.get("title", ""),
        )
        project = d.get("project")
        if project is not None and can_manage_project(request.user, project):
            add_member(project, account, role=MemberRole.MANAGER if account.role == Role.PROJECT_MANAGER else
                       MemberRole.TRAINER if account.role == Role.TRAINER else MemberRole.ANNOTATOR)
        audit.log(request, "employee.create", account, role=account.role, project=project.code if project else None)
        messages.success(request, f"{account.name} was created with employee ID {account.employee_id}."
                         + (" A password-setup email is on its way." if d["send_invite"] else ""))
        return redirect("backoffice:employee_detail", pk=account.pk)
    return render(request, "backoffice/employees/form.html", {
        "page_title": "Add employee",
        "page_subtitle": "The account is approved immediately and gets an employee ID.",
        "crumbs": [("Employees", reverse("backoffice:employee_list")), ("Add employee", None)],
        "form": form,
        "creating": True,
    })


@permission_required_code("employees.view")
def employee_detail(request, pk):
    user = request.user
    employee = get_employee(request, pk)
    tab = request.GET.get("tab", "overview")
    if tab not in dict(TABS):
        tab = "overview"
    ids = scope_ids(user)
    memberships = list(
        project_scope(employee.memberships.select_related("project", "team", "qualified_by"), user, include_global=False)
    )
    can_manage = can_manage_employee(user, employee)
    can_content = has_permission(user, "content.manage")
    can_projects = can_manage and has_permission(user, "projects.manage")
    is_employee = employee.role == Role.EMPLOYEE

    ctx = {
        "page_title": None,
        "crumbs": [("Employees", reverse("backoffice:employee_list")), (employee.name, None)],
        "employee": employee,
        "tab": tab,
        "tabs": TABS,
        "memberships": memberships,
        "can_manage": can_manage,
        "can_change_role": has_permission(user, "staff.manage") and employee.pk != user.pk,
        "can_projects": can_projects,
        "can_content": can_content and employee.status == UserStatus.ACTIVE,
        "role_form": RoleForm(initial={"role": employee.role}),
        "training": training_by_user([employee.pk], ids).get(employee.pk),
        "application": _application(employee) if has_permission(user, "applicants.manage") else None,
        "now": timezone.now(),
    }
    teams_by_project = {}
    for t in Team.objects.filter(project_id__in=[m.project_id for m in memberships]).order_by("name"):
        teams_by_project.setdefault(t.project_id, []).append((t.pk, t.name))
    for m in memberships:
        m.form = MemberUpdateForm(initial={"role": m.role, "team": m.team_id}, project=m.project, prefix=f"m{m.pk}")
        m.form.fields["team"].widget.choices = [("", "No team")] + teams_by_project.get(m.project_id, [])
        m.can_manage = can_projects and can_manage_project(user, m.project)

    if can_projects:
        member_ids = [m.project_id for m in memberships]
        form = MembershipForm(user=user)
        form.fields["project"].queryset = form.fields["project"].queryset.exclude(pk__in=member_ids)
        ctx["membership_form"] = form
    if ctx["can_content"] and is_employee:
        ctx["tutorial_form"] = AssignTutorialForm(tutorials=_assignable_tutorials(user, employee))
        ctx["feedback_form"] = AssignFeedbackForm(feedback=_assignable_feedback(user, employee))
        ctx["test_form"] = AssignTestForm(tests=_assignable_tests(user, employee))

    if tab in ("overview", "onboarding"):
        sections = onboarding_for_user(employee)
        if ids is not None:
            sections = [s for s in sections if s["project"] is None or s["project"].pk in ids]
        ctx["onboarding"] = sections
    if tab == "tutorials":
        ctx["progress_rows"] = list(
            project_scope(TutorialProgress.objects.filter(user=employee), user, field="tutorial__project")
            .select_related("tutorial__project", "tutorial__video", "tutorial__category")
            .order_by("status", "-assigned_at")
        )
    if tab == "feedback":
        rows = list(
            project_scope(FeedbackRecipient.objects.filter(user=employee), user, field="feedback__project")
            .select_related("feedback__project", "feedback__team", "feedback__test").order_by("-feedback__number")
        )
        test_ids = [r.feedback.test_id for r in rows if r.feedback.test_id]
        attempts = {}
        for a in TestAttempt.objects.filter(user=employee, test_id__in=test_ids).order_by("-attempt_number"):
            attempts.setdefault(a.test_id, []).append(a)
        for r in rows:
            r.state = test_state(employee, r.feedback.test, attempts.get(r.feedback.test_id, [])) if r.feedback.test_id else None
        ctx["feedback_rows"] = rows
    if tab == "tests":
        ctx["attempts"] = list(
            project_scope(TestAttempt.objects.filter(user=employee), user, field="test__project")
            .select_related("test__project").order_by("-started_at")
        )
        assignments = list(
            project_scope(TestAssignment.objects.filter(user=employee), user, field="test__project")
            .select_related("test__project", "assigned_by").order_by("-assigned_at")
        )
        by_test = {}
        for a in ctx["attempts"]:
            by_test.setdefault(a.test_id, []).append(a)
        for a in assignments:
            a.state = test_state(employee, a.test, sorted(by_test.get(a.test_id, []), key=lambda x: -x.attempt_number))
        ctx["assignments"] = assignments
    if tab == "overview":
        ctx["recent_attempts"] = list(
            project_scope(TestAttempt.objects.filter(user=employee, submitted_at__isnull=False), user, field="test__project")
            .select_related("test").order_by("-submitted_at")[:5]
        )
        fb = project_scope(FeedbackRecipient.objects.filter(user=employee, feedback__status=ContentStatus.PUBLISHED),
                           user, field="feedback__project")
        ctx["feedback_summary"] = {
            "total": fb.count(), "seen": fb.filter(first_viewed_at__isnull=False).count(),
            "watched": fb.filter(watched_at__isnull=False).count(),
        }
    return render(request, "backoffice/employees/detail.html", ctx)


def _application(employee):
    from apps.website.models import JobApplication

    return JobApplication.objects.filter(user=employee).first()


def _assignable_tutorials(user, employee):
    qs = project_scope(Tutorial.objects.filter(status=ContentStatus.PUBLISHED), user).select_related("project")
    assigned = TutorialProgress.objects.filter(user=employee, assigned=True).values("tutorial_id")
    return qs.exclude(pk__in=assigned).order_by("title")


def _assignable_feedback(user, employee):
    qs = project_scope(Feedback.objects.filter(status=ContentStatus.PUBLISHED), user).select_related("project")
    return qs.exclude(recipients__user=employee).order_by("-number")


def _assignable_tests(user, employee):
    qs = project_scope(Test.objects.filter(status=ContentStatus.PUBLISHED), user).select_related("project")
    return qs.exclude(assignments__user=employee).order_by("title")


def _managed_employee(request, pk):
    employee = get_employee(request, pk)
    if not can_manage_employee(request.user, employee):
        raise PermissionDenied
    return employee


@permission_required_code("employees.manage")
def employee_edit(request, pk):
    employee = _managed_employee(request, pk)
    form = EmployeeEditForm(request.POST or None, instance=employee, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request, "employee.edit", employee, fields=list(form.changed_data))
        messages.success(request, "Profile updated.")
        return redirect("backoffice:employee_detail", pk=employee.pk)
    return render(request, "backoffice/employees/form.html", {
        "page_title": f"Edit {employee.name}",
        "crumbs": [("Employees", reverse("backoffice:employee_list")), (employee.name, reverse("backoffice:employee_detail", args=[employee.pk])), ("Edit", None)],
        "form": form,
        "employee": employee,
    })


@require_POST
@permission_required_code("employees.manage")
def employee_status(request, pk):
    employee = _managed_employee(request, pk)
    action = request.POST.get("action")
    if action == "approve" and employee.status != UserStatus.ACTIVE:
        approve_user(employee, request.user)
        audit.log(request, "employee.approve", employee)
        messages.success(request, f"{employee.name} is approved (ID {employee.employee_id}) and has been notified by email.")
    elif action == "suspend" and employee.status == UserStatus.ACTIVE:
        suspend_user(employee)
        audit.log(request, "employee.suspend", employee)
        messages.success(request, f"{employee.name} has been suspended and signed out everywhere.")
    elif action == "reactivate" and employee.status == UserStatus.SUSPENDED:
        reactivate_user(employee)
        audit.log(request, "employee.reactivate", employee)
        messages.success(request, f"{employee.name} has been reactivated.")
    else:
        messages.error(request, "That action is not available for this account.")
    return redirect_back(request, reverse("backoffice:employee_detail", args=[employee.pk]))


@require_POST
@permission_required_code("staff.manage")
def employee_role(request, pk):
    employee = get_employee(request, pk)
    if employee.pk == request.user.pk:
        raise PermissionDenied
    form = RoleForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a valid role.")
    elif form.cleaned_data["role"] == employee.role:
        messages.info(request, f"{employee.name} already has the role {employee.get_role_display()} — nothing changed.")
    else:
        old = employee.role
        change_role(employee, form.cleaned_data["role"])
        audit.log(request, "employee.role", employee, old=old, new=employee.role)
        messages.success(request, f"{employee.name} is now {employee.get_role_display()}.")
    return redirect("backoffice:employee_detail", pk=employee.pk)


@require_POST
@permission_required_code("employees.manage")
def employee_invite(request, pk):
    employee = _managed_employee(request, pk)
    if employee.status == UserStatus.SUSPENDED:
        messages.error(request, "Reactivate the account before sending a password link.")
        return redirect("backoffice:employee_detail", pk=employee.pk)
    queue_email(
        employee.email, "Set your password", "account_invite",
        {"user": employee, "setup_url": password_setup_url(employee), "login_url": absolute_url(reverse("accounts:login")),
         "invited_by": request.user},
    )
    audit.log(request, "employee.password_link", employee)
    messages.success(request, f"A password-setup link was emailed to {employee.email}.")
    return redirect("backoffice:employee_detail", pk=employee.pk)


@require_POST
@permission_required_code("projects.manage")
def employee_add_project(request, pk):
    employee = _managed_employee(request, pk)
    form = MembershipForm(request.POST, user=request.user)
    if form.is_valid():
        d = form.cleaned_data
        add_member(d["project"], employee, role=d["role"], team=d["team"])
        audit.log(request, "project.member_add", d["project"], user=employee.pk, role=d["role"])
        messages.success(request, f"{employee.name} was added to {d['project'].name}. Its training content is now assigned.")
    else:
        messages.error(request, "Could not add to the project: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("backoffice:employee_detail", pk=employee.pk)


# ── Membership actions (shared by the employee page and the project members tab) ──

def _managed_member(request, pk):
    member = get_object_or_404(ProjectMember.objects.select_related("project", "user", "team"), pk=pk)
    user = request.user
    if not can_manage_project(user, member.project) or not has_permission(user, "projects.manage"):
        raise PermissionDenied
    if member.user.role != Role.EMPLOYEE and not has_permission(user, "staff.manage"):
        raise PermissionDenied
    return member


@require_POST
@permission_required_code("projects.manage")
def member_update(request, pk):
    member = _managed_member(request, pk)
    form = MemberUpdateForm(request.POST, project=member.project, prefix=f"m{member.pk}")
    if form.is_valid():
        add_member(member.project, member.user, role=form.cleaned_data["role"], team=form.cleaned_data["team"])
        audit.log(request, "project.member_update", member.project, user=member.user_id, role=form.cleaned_data["role"],
                  team=form.cleaned_data["team"].pk if form.cleaned_data["team"] else None)
        messages.success(request, f"Updated {member.user.name} on {member.project.code}.")
    else:
        messages.error(request, "Invalid role or team.")
    return redirect_back(request, reverse("backoffice:project_members", args=[member.project_id]))


@require_POST
@permission_required_code("projects.manage")
def member_remove(request, pk):
    member = _managed_member(request, pk)
    remove_member(member.project, member.user)
    audit.log(request, "project.member_remove", member.project, user=member.user_id)
    messages.success(request, f"{member.user.name} was removed from {member.project.name}. Their progress history is kept.")
    return redirect_back(request, reverse("backoffice:project_members", args=[member.project_id]))


@require_POST
@permission_required_code("projects.manage")
def member_qualify(request, pk):
    member = _managed_member(request, pk)
    if request.POST.get("action") == "revoke":
        member.qualified_at, member.qualified_by = None, None
        member.save(update_fields=["qualified_at", "qualified_by"])
        audit.log(request, "project.member_unqualify", member.project, user=member.user_id)
        messages.success(request, f"Qualification revoked for {member.user.name}.")
    elif not member.qualified_at:
        qualify_member(member, request.user)
        audit.log(request, "project.member_qualify", member.project, user=member.user_id)
        messages.success(request, f"{member.user.name} is now qualified for {member.project.name}.")
    return redirect_back(request, reverse("backoffice:project_members", args=[member.project_id]))


# ── Content assignment from the employee page ─────────────────────────────

def _content_employee(request, pk):
    employee = get_employee(request, pk)
    if employee.role != Role.EMPLOYEE or employee.status != UserStatus.ACTIVE:
        messages.error(request, "Content can only be assigned to active employees.")
        return None
    return employee


@require_POST
@permission_required_code("content.manage")
def employee_assign_tutorial(request, pk):
    employee = _content_employee(request, pk)
    if employee:
        form = AssignTutorialForm(request.POST, tutorials=_assignable_tutorials(request.user, employee))
        if form.is_valid():
            tutorial = form.cleaned_data["tutorial"]
            if not can_manage_content_for(request.user, tutorial.project):
                raise PermissionDenied
            assign_tutorial(tutorial, [employee], due_at=day_end(form.cleaned_data["due_date"]))
            audit.log(request, "tutorial.assign", tutorial, users=[employee.pk])
            messages.success(request, f"“{tutorial.title}” was assigned to {employee.name}.")
        else:
            messages.error(request, "Choose a published tutorial to assign.")
    return redirect(reverse("backoffice:employee_detail", args=[pk]) + "?tab=tutorials")


@require_POST
@permission_required_code("content.manage")
def employee_assign_feedback(request, pk):
    employee = _content_employee(request, pk)
    if employee:
        form = AssignFeedbackForm(request.POST, feedback=_assignable_feedback(request.user, employee))
        if form.is_valid():
            fb = form.cleaned_data["feedback"]
            if not can_manage_content_for(request.user, fb.project):
                raise PermissionDenied
            add_recipients(fb, [employee])
            audit.log(request, "feedback.assign", fb, users=[employee.pk])
            messages.success(request, f"Feedback {fb.display_number} was sent to {employee.name}.")
        else:
            messages.error(request, "Choose published feedback to send.")
    return redirect(reverse("backoffice:employee_detail", args=[pk]) + "?tab=feedback")


@require_POST
@permission_required_code("content.manage")
def employee_assign_test(request, pk):
    employee = _content_employee(request, pk)
    if employee:
        form = AssignTestForm(request.POST, tests=_assignable_tests(request.user, employee))
        if form.is_valid():
            test = form.cleaned_data["test"]
            if not can_manage_content_for(request.user, test.project):
                raise PermissionDenied
            assign_test(test, [employee], assigned_by=request.user, due_at=day_end(form.cleaned_data["due_date"]))
            audit.log(request, "test.assign", test, users=[employee.pk])
            messages.success(request, f"“{test.title}” was assigned to {employee.name}.")
        else:
            messages.error(request, "Choose a published test to assign.")
    return redirect(reverse("backoffice:employee_detail", args=[pk]) + "?tab=tests")
