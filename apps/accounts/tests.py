from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.comms.models import EmailMessage
from apps.projects.models import Project
from apps.projects.services import add_member
from apps.training.models import Tutorial, TutorialProgress
from apps.training.services import publish_tutorial

from .models import Role, User, UserStatus
from .permissions import has_permission, project_scope
from .services import approve_user, create_account, suspend_user


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AuthFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("worker@example.com", "S3cure-pass!", name="Worker One", status=UserStatus.PENDING)
        approve_user(self.user, send_email=False)
        self.user.refresh_from_db()

    def test_employee_id_assigned_on_approval(self):
        self.assertRegex(self.user.employee_id, r"^SKY-\d{4}$")

    def test_login_with_email_and_employee_id(self):
        r = self.client.post(reverse("accounts:login"), {"identifier": "WORKER@example.com", "password": "S3cure-pass!"})
        self.assertRedirects(r, reverse("accounts:after_login"), fetch_redirect_response=False)
        self.client.logout()
        r = self.client.post(reverse("accounts:login"), {"identifier": self.user.employee_id.lower(), "password": "S3cure-pass!"})
        self.assertEqual(r.status_code, 302)

    def test_wrong_password_rejected_and_rate_limited(self):
        for _ in range(10):
            r = self.client.post(reverse("accounts:login"), {"identifier": "worker@example.com", "password": "nope"})
            self.assertContains(r, "Incorrect")
        r = self.client.post(reverse("accounts:login"), {"identifier": "worker@example.com", "password": "S3cure-pass!"})
        self.assertContains(r, "Too many sign-in attempts")

    def test_suspended_user_cannot_login_and_is_logged_out(self):
        self.client.force_login(self.user)
        suspend_user(self.user)
        r = self.client.get(reverse("portal:dashboard"))
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("accounts:login"), {"identifier": "worker@example.com", "password": "S3cure-pass!"})
        self.assertContains(r, "suspended")

    def test_open_redirect_blocked(self):
        r = self.client.post(reverse("accounts:login") + "?next=https://evil.example/",
                             {"identifier": "worker@example.com", "password": "S3cure-pass!", "next": "https://evil.example/"})
        self.assertEqual(r["Location"], reverse("accounts:after_login"))

    def test_signup_creates_pending_account_and_alerts_admins(self):
        with self.settings(ADMIN_NOTIFICATION_EMAILS=["boss@example.com"]):
            r = self.client.post(reverse("accounts:signup"), {
                "name": "New Person", "email": "new@example.com", "password1": "Very-strong-9!", "password2": "Very-strong-9!", "agree": "on",
            })
        self.assertRedirects(r, reverse("accounts:pending"))
        u = User.objects.get(email="new@example.com")
        self.assertEqual(u.status, UserStatus.PENDING)
        self.assertIsNone(u.employee_id)
        self.assertTrue(EmailMessage.objects.filter(to="boss@example.com", template="admin_new_signup").exists())
        # pending users cannot reach the portal
        r = self.client.get(reverse("portal:dashboard"))
        self.assertRedirects(r, reverse("accounts:pending"))

    def test_signup_honeypot(self):
        r = self.client.post(reverse("accounts:signup"), {
            "name": "Bot", "email": "bot@example.com", "password1": "Very-strong-9!", "password2": "Very-strong-9!", "agree": "on",
            "website_url": "http://spam",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="bot@example.com").exists())

    def test_password_reset_email(self):
        r = self.client.post(reverse("accounts:password_reset"), {"email": "worker@example.com"})
        self.assertRedirects(r, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/password/set/", mail.outbox[0].body)

    def test_create_account_sends_invite(self):
        admin = User.objects.create_superuser("root@example.com", "x-Strong-123")
        u = create_account(email="invitee@example.com", name="Invitee", invited_by=admin)
        self.assertEqual(u.status, UserStatus.ACTIVE)
        self.assertFalse(u.has_usable_password())
        self.assertTrue(EmailMessage.objects.filter(to="invitee@example.com", template="account_invite").exists())


class PermissionTests(TestCase):
    def test_role_matrix(self):
        def make(role, status=UserStatus.ACTIVE):
            return User.objects.create_user(f"{role}-{status}@example.com", "pw-Strong-1", name=role, role=role, status=status)

        sa, pm, tr, em, cl = (make(r) for r in (Role.SUPER_ADMIN, Role.PROJECT_MANAGER, Role.TRAINER, Role.EMPLOYEE, Role.CLIENT))
        self.assertTrue(has_permission(sa, "settings.manage"))
        self.assertFalse(has_permission(pm, "settings.manage"))
        self.assertTrue(has_permission(pm, "employees.manage"))
        self.assertFalse(has_permission(tr, "employees.manage"))
        self.assertTrue(has_permission(tr, "content.manage"))
        self.assertFalse(has_permission(em, "backoffice.access"))
        self.assertTrue(has_permission(em, "portal.access"))
        self.assertFalse(has_permission(cl, "portal.access"))
        pending = make(Role.PROJECT_MANAGER, UserStatus.PENDING)
        self.assertFalse(has_permission(pending, "backoffice.access"))

    def test_project_scope(self):
        pm = User.objects.create_user("pm@example.com", "pw-Strong-1", name="PM", role=Role.PROJECT_MANAGER, status=UserStatus.ACTIVE)
        mine = Project.objects.create(name="Mine", slug="mine", code="M-1")
        other = Project.objects.create(name="Other", slug="other", code="O-1")
        add_member(mine, pm, notify_user=False)
        t1 = Tutorial.objects.create(title="mine", project=mine)
        Tutorial.objects.create(title="other", project=other)
        t3 = Tutorial.objects.create(title="global")
        self.assertEqual(set(project_scope(Tutorial.objects.all(), pm)), {t1, t3})


class AssignmentOnJoinTests(TestCase):
    def test_joining_project_assigns_published_required_tutorials(self):
        p = Project.objects.create(name="P", slug="p", code="P-1")
        t = Tutorial.objects.create(title="T", project=p, is_required=True)
        publish_tutorial(t)
        emp = User.objects.create_user("e@example.com", "pw-Strong-1", name="E")
        approve_user(emp, send_email=False)
        add_member(p, emp, notify_user=False)
        self.assertTrue(TutorialProgress.objects.filter(tutorial=t, user=emp, assigned=True).exists())


class ChangeRoleTests(TestCase):
    def test_promotion_and_demotion_sync_django_admin_flags(self):
        from .services import change_role

        u = User.objects.create_user("r@example.com", "pw-Strong-1", name="R", status=UserStatus.ACTIVE)
        change_role(u, Role.SUPER_ADMIN)
        self.assertTrue(u.is_staff and u.is_superuser)
        change_role(u, Role.PROJECT_MANAGER)
        u.refresh_from_db()
        self.assertFalse(u.is_staff or u.is_superuser)
        self.assertTrue(u.employee_id)
