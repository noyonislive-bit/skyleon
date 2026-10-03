"""Project membership — adding someone to a project assigns them its training content."""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.comms.models import NotificationType
from apps.comms.services import notify

from .models import MemberRole, ProjectMember


@transaction.atomic
def add_member(project, user, *, role=MemberRole.ANNOTATOR, team=None, notify_user=True) -> ProjectMember:
    member, created = ProjectMember.objects.get_or_create(
        project=project, user=user, defaults={"role": role, "team": team}
    )
    if not created and (member.role != role or member.team_id != (team.pk if team else None)):
        member.role, member.team = role, team
        member.save(update_fields=["role", "team"])
    if user.is_employee and user.is_approved:
        sync_member_content(member)
        if created and notify_user:
            notify(
                user, NotificationType.PROJECT, f"You've been added to {project.name}",
                "Your project training, guidelines and onboarding are now available.",
                reverse("portal:project_detail", args=[project.slug]),
                email_template="project_assigned", email_subject=f"You have been assigned to {project.name}",
                context={"project": project},
            )
    return member


def sync_member_content(member: ProjectMember) -> dict:
    from apps.assessments.services import sync_member_tests
    from apps.feedback.services import sync_member_feedback
    from apps.training.services import sync_member_tutorials

    return {
        "tutorials": sync_member_tutorials(member.user, member.project),
        "feedback": sync_member_feedback(member.user, member.project, member.team),
        "tests": sync_member_tests(member.user, member.project),
    }


def remove_member(project, user) -> None:
    ProjectMember.objects.filter(project=project, user=user).delete()


def qualify_member(member: ProjectMember, by_user) -> ProjectMember:
    member.qualified_at = timezone.now()
    member.qualified_by = by_user
    member.save(update_fields=["qualified_at", "qualified_by"])
    notify(
        member.user, NotificationType.PROJECT, f"You are qualified for {member.project.name}",
        "Congratulations — you have completed onboarding and are qualified for production work.",
        reverse("portal:project_detail", args=[member.project.slug]),
    )
    return member
