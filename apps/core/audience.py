"""Who should receive project content."""

from django.contrib.auth import get_user_model

from apps.accounts.models import Role, UserStatus


def active_employees():
    return get_user_model().objects.filter(role=Role.EMPLOYEE, status=UserStatus.ACTIVE)


def project_audience(project, team=None):
    """Active employees who are members of the project (optionally a single team)."""
    if project is None:
        return active_employees()
    qs = active_employees().filter(memberships__project=project)
    if team is not None:
        qs = qs.filter(memberships__team=team)
    return qs.distinct()
