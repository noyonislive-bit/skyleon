"""
Role-based access control.

Roles → permission codes. Views check codes with @permission_required_code /
PermissionRequiredMixin. Project-scoped staff (Project Manager, Trainer/QA)
are additionally limited to the projects they belong to — see `project_scope`.
"""

from .models import Role

SA, PM, TR, EM, CL = Role.SUPER_ADMIN, Role.PROJECT_MANAGER, Role.TRAINER, Role.EMPLOYEE, Role.CLIENT

PERMISSIONS: dict[str, set[str]] = {
    # Areas
    "backoffice.access": {SA, PM, TR},
    "portal.access": {SA, PM, TR, EM},
    "client_portal.access": {CL},
    # People
    "employees.view": {SA, PM, TR},
    "employees.manage": {SA, PM},  # approve, suspend, edit, assign projects/training
    "staff.manage": {SA},  # create staff accounts, change roles
    "applicants.manage": {SA, PM},
    # Business
    "leads.manage": {SA},  # quote requests + contact messages
    "clients.manage": {SA},  # client organisations + client portal accounts
    # Projects
    "projects.create": {SA},
    "projects.manage": {SA, PM},  # edit, members, teams, guidelines (scoped for PM)
    # Training content (scoped for PM / Trainer)
    "content.manage": {SA, PM, TR},  # tutorials, feedback, tests, onboarding steps
    "announcements.manage": {SA, PM, TR},
    "meetings.manage": {SA, PM, TR},
    # Insight
    "reports.view": {SA, PM, TR},
    "emails.view": {SA},
    "settings.manage": {SA},
    "audit.view": {SA},
}


def has_permission(user, code: str) -> bool:
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.status != "active":
        return False
    return user.role in PERMISSIONS.get(code, set())


def is_unscoped(user) -> bool:
    """Super admins see every project; other staff only their own."""
    return user.role == Role.SUPER_ADMIN


def scoped_project_ids(user):
    """None = all projects; otherwise the list of project ids the user belongs to."""
    if is_unscoped(user):
        return None
    from apps.projects.models import ProjectMember

    return list(ProjectMember.objects.filter(user=user).values_list("project_id", flat=True))


def project_scope(qs, user, field: str = "project", include_global: bool = True):
    """
    Restrict a queryset of project-owned objects to the user's projects.
    `include_global` keeps rows whose project is NULL (company-wide content).
    """
    ids = scoped_project_ids(user)
    if ids is None:
        return qs
    from django.db.models import Q

    cond = Q(**{f"{field}__in": ids})
    if include_global:
        cond |= Q(**{f"{field}__isnull": True})
    return qs.filter(cond)


def can_manage_project(user, project) -> bool:
    if not has_permission(user, "projects.manage") and not has_permission(user, "content.manage"):
        return False
    ids = scoped_project_ids(user)
    return ids is None or (project is not None and project.pk in ids)


def can_manage_content_for(user, project) -> bool:
    """Content with project=None is company-wide: only unscoped staff or trainers may edit it."""
    if not has_permission(user, "content.manage"):
        return False
    if project is None:
        return user.role in {SA, TR}
    ids = scoped_project_ids(user)
    return ids is None or project.pk in ids
