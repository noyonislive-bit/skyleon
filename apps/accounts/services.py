"""Account lifecycle: signup, approval, invitations, suspension."""

from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.comms.models import NotificationType
from apps.comms.services import absolute_url, notify, notify_admins, queue_email

from .models import Role, User, UserStatus


def password_setup_url(user: User) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return absolute_url(reverse("accounts:password_reset_confirm", args=[uid, token]))


def ensure_employee_id(user: User) -> str:
    if not user.employee_id:
        while True:
            candidate = user.assign_employee_id(save=False)
            if not User.objects.filter(employee_id=candidate).exclude(pk=user.pk).exists():
                break
        user.save(update_fields=["employee_id", "updated_at"])
    return user.employee_id


def notify_new_signup(user: User):
    notify_admins(
        f"New employee signup: {user.name}", "admin_new_signup",
        {"applicant": user, "review_url": absolute_url(reverse("backoffice:employee_detail", args=[user.pk]))},
    )


@transaction.atomic
def approve_user(user: User, by: User | None = None, *, send_email=True) -> User:
    from apps.training.services import sync_global_tutorials

    was_pending = user.status != UserStatus.ACTIVE
    user.status = UserStatus.ACTIVE
    user.approved_at = user.approved_at or timezone.now()
    user.approved_by = user.approved_by or by
    user.suspended_at = None
    user.save()
    if user.role != Role.CLIENT:
        ensure_employee_id(user)
    if user.role == Role.EMPLOYEE:
        sync_global_tutorials(user)
        from apps.projects.services import sync_member_content

        for member in user.memberships.select_related("project", "team"):
            sync_member_content(member)
    if was_pending and send_email:
        context = {
            "user": user,
            "login_url": absolute_url(reverse("accounts:login")),
            "setup_url": password_setup_url(user) if not user.has_usable_password() else None,
        }
        queue_email(user.email, "Your account has been approved", "account_approved", context)
        notify(user, NotificationType.ACCOUNT, "Welcome aboard!", "Your account has been approved.", reverse("portal:dashboard"))
    return user


def suspend_user(user: User) -> User:
    user.status = UserStatus.SUSPENDED
    user.suspended_at = timezone.now()
    user.save()
    _end_sessions(user)
    return user


def reactivate_user(user: User) -> User:
    user.status = UserStatus.ACTIVE
    user.suspended_at = None
    user.save()
    return user


def _end_sessions(user: User):
    """Delete every DB session belonging to the user (logs them out everywhere)."""
    from django.contrib.sessions.models import Session

    for s in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if str(s.get_decoded().get("_auth_user_id")) == str(user.pk):
            s.delete()


@transaction.atomic
def create_account(*, email, name, role=Role.EMPLOYEE, invited_by=None, approve=True, send_invite=True, **fields) -> User:
    """Create an account from the admin panel (or from an approved job application) and email a set-password link."""
    user = User.objects.create_user(email=email, password=None, name=name, role=role, **fields)
    if approve:
        approve_user(user, invited_by, send_email=False)
    if send_invite:
        queue_email(
            user.email, f"Your {('employee' if role == Role.EMPLOYEE else 'staff')} account is ready", "account_invite",
            {"user": user, "setup_url": password_setup_url(user), "login_url": absolute_url(reverse("accounts:login")), "invited_by": invited_by},
        )
    return user


@transaction.atomic
def convert_application(application, by: User) -> User:
    from apps.website.models import ApplicationStatus

    existing = User.objects.filter(email__iexact=application.email).first()
    user = existing or create_account(
        email=application.email, name=application.full_name, invited_by=by, phone=application.phone or "",
        location=application.location or "", skills=application.skills or [],
    )
    if existing and existing.status != UserStatus.ACTIVE:
        approve_user(existing, by)
    application.user = user
    application.status = ApplicationStatus.APPROVED
    application.save(update_fields=["user", "status", "updated_at"])
    return user
