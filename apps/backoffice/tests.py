"""
Admin panel tests: permission matrix, project scoping and the key POST flows.

    DB_TEST_NAME=test_skyleon_admin python manage.py test apps.backoffice
"""

import shutil
import tempfile
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User, UserStatus
from apps.assessments.models import Question, QuestionOption, QuestionType, Test, TestAssignment, TestAttempt, TestKind
from apps.assessments.services import start_attempt, submit_attempt
from apps.comms.models import Announcement, EmailMessage, EmailStatus, Meeting, MeetingInvite, Notification
from apps.core.choices import ContentStatus, ProgressStatus
from apps.core.models import AuditLog
from apps.core import site_settings
from apps.feedback.models import Feedback, FeedbackRecipient
from apps.projects.models import MemberRole, Project, ProjectMember, Team
from apps.projects.services import add_member
from apps.storage.models import MediaAsset, MediaKind, MediaStatus
from apps.training.models import OnboardingStep, Tutorial, TutorialCategory, TutorialProgress
from apps.training.services import publish_tutorial
from apps.website.models import ContactMessage, JobApplication, LeadStatus, QuoteRequest

TMP = tempfile.mkdtemp(prefix="skyleon-admin-tests-")
STATIC = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(
    STORAGES=STATIC, EMAIL_SEND_IMMEDIATELY=False, STORAGE_BACKEND="local", PRIVATE_STORAGE_DIR=TMP,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AdminTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        def make(email, role, status=UserStatus.ACTIVE, **extra):
            u = User.objects.create_user(email=email, password="x", name=email.split("@")[0].title(), role=role, status=status, **extra)
            if status == UserStatus.ACTIVE:
                u.assign_employee_id()
            return u

        cls.admin = make("admin@t.test", Role.SUPER_ADMIN)
        cls.pm = make("pm@t.test", Role.PROJECT_MANAGER)
        cls.trainer = make("trainer@t.test", Role.TRAINER)
        cls.emp1 = make("emp1@t.test", Role.EMPLOYEE)
        cls.emp2 = make("emp2@t.test", Role.EMPLOYEE)
        cls.other = make("other@t.test", Role.EMPLOYEE)  # member of P2 only
        cls.loner = make("loner@t.test", Role.EMPLOYEE)  # no project (unassigned pool)
        cls.pending = make("pending@t.test", Role.EMPLOYEE, status=UserStatus.PENDING)
        cls.client_user = make("client@t.test", Role.CLIENT)

        cls.p1 = Project.objects.create(name="Project One", slug="p1", code="P1-01")
        cls.p2 = Project.objects.create(name="Project Two", slug="p2", code="P2-02")
        cls.team_a = Team.objects.create(project=cls.p1, name="Team A")
        for u, role in ((cls.pm, MemberRole.MANAGER), (cls.trainer, MemberRole.TRAINER)):
            add_member(cls.p1, u, role=role, notify_user=False)
        add_member(cls.p1, cls.emp1, team=cls.team_a, notify_user=False)
        add_member(cls.p1, cls.emp2, notify_user=False)
        add_member(cls.p2, cls.other, notify_user=False)

        cls.video = MediaAsset.objects.create(kind=MediaKind.VIDEO, provider="external", external_url="https://cdn.example/v.mp4",
                                              status=MediaStatus.READY, duration_sec=30)
        cls.cat = TutorialCategory.objects.create(name="Basics", slug="basics")
        cls.tut1 = Tutorial.objects.create(title="P1 tutorial", project=cls.p1, video=cls.video, category=cls.cat)
        publish_tutorial(cls.tut1)
        cls.tut2 = Tutorial.objects.create(title="P2 tutorial", project=cls.p2, video=cls.video)
        publish_tutorial(cls.tut2)

        cls.fb1 = Feedback.objects.create(topic="Boxes too loose", project=cls.p1, explanation="Tight boxes.", created_by=cls.trainer)
        cls.fb2 = Feedback.objects.create(topic="P2 issue", project=cls.p2, explanation="…")

        cls.test1 = Test.objects.create(title="P1 test", project=cls.p1, kind=TestKind.TRAINING, passing_score=50)
        q = Question.objects.create(test=cls.test1, prompt="2+2?", qtype=QuestionType.SINGLE_CHOICE)
        cls.q_ok = QuestionOption.objects.create(question=q, text="4", is_correct=True)
        QuestionOption.objects.create(question=q, text="5")
        cls.test2 = Test.objects.create(title="P2 test", project=cls.p2)

        cls.quote = QuoteRequest.objects.create(name="Lead", email="lead@x.test", project_type="Video annotation")
        cls.message = ContactMessage.objects.create(name="Msg", email="m@x.test", message="Hello")
        cls.application = JobApplication.objects.create(full_name="Appl Icant", email="applicant@x.test", phone="1", location="Remote")

    def setUp(self):
        cache.clear()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def get(self, user, name, *args, **query):
        self.client.force_login(user)
        url = reverse(f"backoffice:{name}", args=args)
        return self.client.get(url, query)

    def post(self, user, name, *args, data=None):
        self.client.force_login(user)
        return self.client.post(reverse(f"backoffice:{name}", args=args), data or {})


class PermissionMatrixTests(AdminTestCase):
    STAFF_PAGES = ["dashboard", "employee_list", "project_list", "tutorial_list", "feedback_list", "feedback_tracking",
                   "test_list", "training_progress", "reports", "announcement_list", "meeting_list", "category_list"]

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("backoffice:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_employee_and_client_are_denied(self):
        for user in (self.emp1, self.client_user):
            for name in ("dashboard", "employee_list", "tutorial_list", "settings"):
                self.assertEqual(self.get(user, name).status_code, 403, (user.email, name))

    def test_pending_user_redirected(self):
        response = self.get(self.pending, "dashboard")
        self.assertRedirects(response, reverse("accounts:pending"), fetch_redirect_response=False)

    def test_all_staff_pages_render(self):
        for user in (self.admin, self.pm, self.trainer):
            for name in self.STAFF_PAGES:
                self.assertEqual(self.get(user, name).status_code, 200, (user.email, name))

    def test_super_admin_only_pages(self):
        for name in ("lead_list", "message_list", "email_list", "settings", "audit_log"):
            self.assertEqual(self.get(self.admin, name).status_code, 200, name)
            self.assertEqual(self.get(self.pm, name).status_code, 403, name)
            self.assertEqual(self.get(self.trainer, name).status_code, 403, name)
        self.assertEqual(self.get(self.admin, "lead_detail", self.quote.pk).status_code, 200)
        self.assertEqual(self.get(self.pm, "lead_detail", self.quote.pk).status_code, 403)
        self.assertEqual(self.get(self.admin, "message_detail", self.message.pk).status_code, 200)

    def test_applicants_for_admin_and_pm_only(self):
        self.assertEqual(self.get(self.admin, "applicant_detail", self.application.pk).status_code, 200)
        self.assertEqual(self.get(self.pm, "applicant_list").status_code, 200)
        self.assertEqual(self.get(self.trainer, "applicant_list").status_code, 403)

    def test_trainer_cannot_manage_people_or_create_projects(self):
        self.assertEqual(self.get(self.trainer, "employee_create").status_code, 403)
        self.assertEqual(self.post(self.trainer, "employee_status", self.emp1.pk, data={"action": "suspend"}).status_code, 403)
        self.assertEqual(self.get(self.pm, "project_create").status_code, 403)
        self.assertEqual(self.get(self.admin, "project_create").status_code, 200)

    def test_sidebar_shows_only_permitted_links(self):
        html = self.get(self.trainer, "dashboard").content.decode()
        self.assertIn(reverse("backoffice:tutorial_list"), html)
        self.assertNotIn(reverse("backoffice:lead_list"), html)
        self.assertNotIn(reverse("backoffice:settings"), html)
        self.assertNotIn(reverse("backoffice:applicant_list"), html)
        html = self.get(self.admin, "dashboard").content.decode()
        for name in ("lead_list", "settings", "email_list", "applicant_list"):
            self.assertIn(reverse(f"backoffice:{name}"), html)


class ScopeTests(AdminTestCase):
    def test_pm_sees_only_own_projects(self):
        self.assertEqual(self.get(self.pm, "project_detail", self.p1.pk).status_code, 200)
        self.assertEqual(self.get(self.pm, "project_detail", self.p2.pk).status_code, 404)
        self.assertEqual(self.get(self.pm, "project_members", self.p2.pk).status_code, 404)
        html = self.get(self.pm, "project_list").content.decode()
        self.assertIn("Project One", html)
        self.assertNotIn("Project Two", html)

    def test_employee_scope_for_pm_and_trainer(self):
        # PM: own project members + the unassigned pool (pending signups, employees without a project)
        for target, expected in ((self.emp1, 200), (self.loner, 200), (self.pending, 200), (self.other, 404), (self.admin, 404)):
            self.assertEqual(self.get(self.pm, "employee_detail", target.pk).status_code, expected, target.email)
        # Trainer: only members of their projects
        for target, expected in ((self.emp1, 200), (self.loner, 404), (self.other, 404)):
            self.assertEqual(self.get(self.trainer, "employee_detail", target.pk).status_code, expected, target.email)
        html = self.get(self.pm, "employee_list").content.decode()
        self.assertIn(self.emp1.email, html)
        self.assertNotIn(self.other.email, html)

    def test_content_scope(self):
        self.assertEqual(self.get(self.trainer, "tutorial_detail", self.tut1.pk).status_code, 200)
        self.assertEqual(self.get(self.trainer, "tutorial_detail", self.tut2.pk).status_code, 404)
        self.assertEqual(self.get(self.trainer, "feedback_detail", self.fb2.pk).status_code, 404)
        self.assertEqual(self.get(self.trainer, "test_builder", self.test2.pk).status_code, 404)
        self.assertEqual(self.get(self.pm, "test_results", self.test2.pk).status_code, 404)
        self.assertEqual(self.get(self.admin, "test_builder", self.test2.pk).status_code, 200)
        # A PM can view company-wide tutorials but not edit them
        glob = Tutorial.objects.create(title="Company wide", video=self.video)
        self.assertEqual(self.get(self.pm, "tutorial_detail", glob.pk).status_code, 200)
        self.assertEqual(self.get(self.pm, "tutorial_edit", glob.pk).status_code, 403)
        self.assertEqual(self.get(self.trainer, "tutorial_edit", glob.pk).status_code, 200)

    def test_pm_cannot_post_feedback_for_other_project(self):
        response = self.post(self.pm, "feedback_create", data={
            "topic": "X", "explanation": "Y", "project": self.p2.pk, "severity": "normal", "cadence": "daily", "then": "save",
        })
        self.assertEqual(response.status_code, 200)  # form re-rendered with an error
        self.assertFalse(Feedback.objects.filter(topic="X").exists())

    def test_dashboard_figures_are_scoped(self):
        response = self.get(self.pm, "dashboard")
        tiles = {t["label"]: t["value"] for t in response.context["tiles"]}
        # emp1, emp2 (P1) + loner + pending (unassigned pool); not `other` (P2)
        self.assertEqual(tiles["Total employees"], 4)
        self.assertEqual(tiles["Active projects"], 1)
        self.assertIn("New applicants", tiles)  # PMs manage applicants
        trainer_tiles = {t["label"] for t in self.get(self.trainer, "dashboard").context["tiles"]}
        self.assertNotIn("New applicants", trainer_tiles)
        admin_tiles = {t["label"]: t["value"] for t in self.get(self.admin, "dashboard").context["tiles"]}
        self.assertEqual(admin_tiles["Total employees"], 5)
        self.assertEqual(admin_tiles["Active projects"], 2)

    def test_pm_cannot_change_roles_or_manage_staff(self):
        self.assertEqual(self.post(self.pm, "employee_role", self.emp1.pk, data={"role": Role.SUPER_ADMIN}).status_code, 403)
        self.emp1.refresh_from_db()
        self.assertEqual(self.emp1.role, Role.EMPLOYEE)


class PeopleActionTests(AdminTestCase):
    def test_approve_pending_employee(self):
        response = self.post(self.pm, "employee_status", self.pending.pk, data={"action": "approve"})
        self.assertRedirects(response, reverse("backoffice:employee_detail", args=[self.pending.pk]), fetch_redirect_response=False)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, UserStatus.ACTIVE)
        self.assertTrue(self.pending.employee_id)
        self.assertTrue(EmailMessage.objects.filter(to=self.pending.email, template="account_approved").exists())
        self.assertTrue(AuditLog.objects.filter(action="employee.approve", entity_id=str(self.pending.pk)).exists())

    def test_suspend_and_reactivate(self):
        self.post(self.admin, "employee_status", self.emp2.pk, data={"action": "suspend"})
        self.emp2.refresh_from_db()
        self.assertEqual(self.emp2.status, UserStatus.SUSPENDED)
        self.post(self.admin, "employee_status", self.emp2.pk, data={"action": "approve"})  # not a back door
        self.emp2.refresh_from_db()
        self.assertEqual(self.emp2.status, UserStatus.SUSPENDED)
        self.post(self.admin, "employee_status", self.emp2.pk, data={"action": "reactivate"})
        self.emp2.refresh_from_db()
        self.assertEqual(self.emp2.status, UserStatus.ACTIVE)

    def test_create_employee_pm_only_employees(self):
        response = self.post(self.pm, "employee_create", data={
            "name": "New Person", "email": "new@t.test", "role": Role.SUPER_ADMIN, "project": self.p1.pk, "send_invite": "on",
        })
        self.assertEqual(response.status_code, 200)  # role rejected for a PM
        response = self.post(self.pm, "employee_create", data={
            "name": "New Person", "email": "new@t.test", "role": Role.EMPLOYEE, "project": self.p1.pk, "send_invite": "on",
        })
        user = User.objects.get(email="new@t.test")
        self.assertRedirects(response, reverse("backoffice:employee_detail", args=[user.pk]), fetch_redirect_response=False)
        self.assertEqual(user.status, UserStatus.ACTIVE)
        self.assertTrue(ProjectMember.objects.filter(project=self.p1, user=user).exists())
        self.assertTrue(TutorialProgress.objects.filter(user=user, tutorial=self.tut1, assigned=True).exists())
        self.assertTrue(EmailMessage.objects.filter(to="new@t.test", template="account_invite").exists())

    def test_admin_creates_staff_and_changes_role(self):
        self.post(self.admin, "employee_create", data={"name": "Trainer Two", "email": "t2@t.test", "role": Role.TRAINER})
        self.assertEqual(User.objects.get(email="t2@t.test").role, Role.TRAINER)
        self.post(self.admin, "employee_role", self.emp2.pk, data={"role": Role.TRAINER})
        self.emp2.refresh_from_db()
        self.assertEqual(self.emp2.role, Role.TRAINER)

    def test_password_link(self):
        self.post(self.pm, "employee_invite", self.emp1.pk)
        self.assertTrue(EmailMessage.objects.filter(to=self.emp1.email, template="account_invite").exists())

    def test_add_member_and_update_remove_qualify(self):
        response = self.post(self.pm, "project_members", self.p1.pk, data={"users": [self.loner.pk], "role": MemberRole.REVIEWER, "team": self.team_a.pk})
        self.assertRedirects(response, reverse("backoffice:project_members", args=[self.p1.pk]), fetch_redirect_response=False)
        member = ProjectMember.objects.get(project=self.p1, user=self.loner)
        self.assertEqual(member.role, MemberRole.REVIEWER)
        self.assertEqual(member.team, self.team_a)
        self.assertTrue(TutorialProgress.objects.filter(user=self.loner, tutorial=self.tut1).exists())
        # PM cannot add someone from another project
        self.post(self.pm, "project_members", self.p1.pk, data={"users": [self.other.pk], "role": MemberRole.ANNOTATOR})
        self.assertFalse(ProjectMember.objects.filter(project=self.p1, user=self.other).exists())

        self.post(self.pm, "member_update", member.pk, data={f"m{member.pk}-role": MemberRole.QA, f"m{member.pk}-team": ""})
        member.refresh_from_db()
        self.assertEqual((member.role, member.team_id), (MemberRole.QA, None))
        self.post(self.pm, "member_qualify", member.pk)
        member.refresh_from_db()
        self.assertIsNotNone(member.qualified_at)
        self.post(self.pm, "member_remove", member.pk)
        self.assertFalse(ProjectMember.objects.filter(pk=member.pk).exists())

    def test_trainer_cannot_add_members(self):
        response = self.post(self.trainer, "project_members", self.p1.pk, data={"users": [self.loner.pk], "role": MemberRole.ANNOTATOR})
        self.assertEqual(response.status_code, 403)

    def test_assign_tutorial_feedback_test_from_employee_page(self):
        Tutorial.objects.filter(pk=self.tut1.pk).update(is_required=False)
        TutorialProgress.objects.filter(user=self.emp2, tutorial=self.tut1).delete()
        self.post(self.trainer, "employee_assign_tutorial", self.emp2.pk, data={"tutorial": self.tut1.pk, "due_date": "2030-01-31"})
        p = TutorialProgress.objects.get(user=self.emp2, tutorial=self.tut1)
        self.assertTrue(p.assigned)
        self.assertEqual(p.due_at.date().isoformat(), "2030-01-31")
        Feedback.objects.filter(pk=self.fb1.pk).update(status=ContentStatus.PUBLISHED)
        self.post(self.trainer, "employee_assign_feedback", self.emp2.pk, data={"feedback": self.fb1.pk})
        self.assertTrue(FeedbackRecipient.objects.filter(user=self.emp2, feedback=self.fb1).exists())
        Test.objects.filter(pk=self.test1.pk).update(status=ContentStatus.PUBLISHED)
        self.post(self.trainer, "employee_assign_test", self.emp2.pk, data={"test": self.test1.pk})
        self.assertTrue(TestAssignment.objects.filter(user=self.emp2, test=self.test1).exists())

    def test_convert_application(self):
        response = self.post(self.pm, "applicant_convert", self.application.pk)
        user = User.objects.get(email="applicant@x.test")
        self.assertRedirects(response, reverse("backoffice:employee_detail", args=[user.pk]), fetch_redirect_response=False)
        self.application.refresh_from_db()
        self.assertEqual(self.application.user, user)
        self.assertEqual(user.status, UserStatus.ACTIVE)

    def test_lead_status_update_and_csv(self):
        self.post(self.admin, "lead_detail", self.quote.pk, data={"status": LeadStatus.QUALIFIED, "notes": "Call on Monday"})
        self.quote.refresh_from_db()
        self.assertEqual((self.quote.status, self.quote.notes), (LeadStatus.QUALIFIED, "Call on Monday"))
        response = self.get(self.admin, "lead_list", format="csv")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        body = response.content.decode("utf-8-sig")
        self.assertTrue(body.startswith("ID,Received,Name,Company,Email"))
        self.assertIn("lead@x.test", body)


class ContentActionTests(AdminTestCase):
    def test_create_and_publish_tutorial_with_uploaded_video(self):
        asset = MediaAsset.objects.create(kind=MediaKind.VIDEO, provider="local", storage_key="tutorial/x.mp4",
                                          status=MediaStatus.READY, duration_sec=12, uploaded_by=self.trainer)
        response = self.post(self.trainer, "tutorial_create", data={
            "title": "New tutorial", "description": "**Hi**", "project": self.p1.pk, "cadence": "daily",
            "is_required": "on", "video": str(asset.pk), "then": "publish",
        })
        tutorial = Tutorial.objects.get(title="New tutorial")
        self.assertRedirects(response, reverse("backoffice:tutorial_detail", args=[tutorial.pk]), fetch_redirect_response=False)
        self.assertEqual(tutorial.video, asset)
        self.assertEqual(tutorial.status, ContentStatus.PUBLISHED)
        self.assertEqual(set(TutorialProgress.objects.filter(tutorial=tutorial).values_list("user_id", flat=True)), {self.emp1.pk, self.emp2.pk})

    def test_tutorial_rejects_unknown_asset(self):
        response = self.post(self.trainer, "tutorial_create", data={
            "title": "Bad", "project": self.p1.pk, "cadence": "daily", "video": "00000000-0000-0000-0000-000000000000",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Tutorial.objects.filter(title="Bad").exists())

    def test_tutorial_tracking_table(self):
        TutorialProgress.objects.filter(user=self.emp1, tutorial=self.tut1).update(status=ProgressStatus.COMPLETED, percent=100, completed_at=timezone.now())
        response = self.get(self.trainer, "tutorial_detail", self.tut1.pk, status="watched")
        self.assertContains(response, self.emp1.name)
        self.assertNotContains(response, self.emp2.email)

    def test_publish_feedback_and_tracking(self):
        response = self.post(self.trainer, "feedback_publish", self.fb1.pk)
        self.assertRedirects(response, reverse("backoffice:feedback_detail", args=[self.fb1.pk]), fetch_redirect_response=False)
        self.fb1.refresh_from_db()
        self.assertEqual(self.fb1.status, ContentStatus.PUBLISHED)
        self.assertEqual(set(self.fb1.recipients.values_list("user_id", flat=True)), {self.emp1.pk, self.emp2.pk})
        self.assertTrue(Notification.objects.filter(user=self.emp1, title__contains=self.fb1.display_number).exists())
        page = self.get(self.trainer, "feedback_detail", self.fb1.pk)
        self.assertContains(page, "Pending")

    def test_feedback_test_flow(self):
        response = self.post(self.trainer, "feedback_test_create", self.fb1.pk)
        self.fb1.refresh_from_db()
        test = self.fb1.test
        self.assertEqual((test.kind, test.project), (TestKind.FEEDBACK, self.p1))
        self.assertIn(reverse("backoffice:test_builder", args=[test.pk]), response["Location"])
        # Publishing is blocked while the test has no questions
        self.post(self.trainer, "feedback_publish", self.fb1.pk)
        self.fb1.refresh_from_db()
        self.assertEqual(self.fb1.status, ContentStatus.DRAFT)
        self._add_single_question(test)
        self.post(self.trainer, "feedback_publish", self.fb1.pk)
        self.fb1.refresh_from_db()
        test.refresh_from_db()
        self.assertEqual((self.fb1.status, test.status), (ContentStatus.PUBLISHED, ContentStatus.PUBLISHED))
        self.assertEqual(TestAssignment.objects.filter(test=test).count(), 2)
        # Results: emp1 passes → tracking shows Passed with the score
        attempt = start_attempt(self.emp1, test)
        q = test.questions.first()
        submit_attempt(attempt, {str(q.pk): [q.options.get(is_correct=True).pk]})
        FeedbackRecipient.objects.filter(feedback=self.fb1, user=self.emp1).update(watched_at=timezone.now(), first_viewed_at=timezone.now())
        page = self.get(self.trainer, "feedback_tracking", project=self.p1.pk, state="completed")
        self.assertEqual([r.user_id for r in page.context["page"]], [self.emp1.pk])
        self.assertEqual(page.context["page"][0].result, "passed")
        csv = self.get(self.trainer, "feedback_tracking", format="csv")
        body = csv.content.decode("utf-8-sig").splitlines()
        self.assertTrue(body[0].startswith("Employee,Employee ID,Email,Feedback"))
        self.assertTrue(any("Passed" in line and self.emp1.email in line for line in body))
        low = self.get(self.trainer, "feedback_tracking", score_max="50")
        self.assertEqual(len(low.context["page"]), 0)

    def _add_single_question(self, test, prompt="Pick A"):
        return self.post(self.trainer, "question_create", test.pk, data={
            "q-qtype": QuestionType.SINGLE_CHOICE, "q-prompt": prompt, "q-points": 1, "q-explanation": "",
            "opt-TOTAL_FORMS": 3, "opt-INITIAL_FORMS": 0, "opt-MIN_NUM_FORMS": 0, "opt-MAX_NUM_FORMS": 12,
            "opt-0-text": "A", "opt-0-is_correct": "on", "opt-1-text": "B", "opt-2-text": "",
        })

    def test_create_test_with_questions(self):
        response = self.post(self.trainer, "test_create", data={
            "title": "Built test", "kind": TestKind.TRAINING, "project": self.p1.pk, "passing_score": 80, "reveal_answers": "on",
        })
        test = Test.objects.get(title="Built test")
        self.assertIn(reverse("backoffice:test_builder", args=[test.pk]), response["Location"])
        self._add_single_question(test)
        q = test.questions.get()
        self.assertEqual(list(q.options.values_list("text", "is_correct")), [("A", True), ("B", False)])

        # single choice with two correct answers → rejected
        response = self.post(self.trainer, "question_create", test.pk, data={
            "q-qtype": QuestionType.SINGLE_CHOICE, "q-prompt": "Bad", "q-points": 1,
            "opt-TOTAL_FORMS": 2, "opt-INITIAL_FORMS": 0, "opt-0-text": "A", "opt-0-is_correct": "on", "opt-1-text": "B", "opt-1-is_correct": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "exactly one correct option")
        # fewer than two options → rejected
        response = self.post(self.trainer, "question_create", test.pk, data={
            "q-qtype": QuestionType.MULTI_SELECT, "q-prompt": "Bad 2", "q-points": 1,
            "opt-TOTAL_FORMS": 1, "opt-INITIAL_FORMS": 0, "opt-0-text": "A", "opt-0-is_correct": "on",
        })
        self.assertContains(response, "at least two answer options")
        # true / false creates its own options
        self.post(self.trainer, "question_create", test.pk, data={
            "q-qtype": QuestionType.TRUE_FALSE, "q-prompt": "Sky is blue", "q-points": 2, "q-tf_answer": "true",
            "opt-TOTAL_FORMS": 0, "opt-INITIAL_FORMS": 0,
        })
        tf = test.questions.get(prompt="Sky is blue")
        self.assertEqual(list(tf.options.values_list("text", "is_correct")), [("সত্য", True), ("মিথ্যা", False)])  # employees read them
        # multi-select with an image option (uploaded by the trainer through the upload widget)
        img = MediaAsset.objects.create(kind=MediaKind.IMAGE, provider="local", storage_key="option/a.png", status=MediaStatus.READY,
                                        uploaded_by=self.trainer)
        self.post(self.trainer, "question_create", test.pk, data={
            "q-qtype": QuestionType.MULTI_SELECT, "q-prompt": "Which masks are correct?", "q-points": 1,
            "opt-TOTAL_FORMS": 3, "opt-INITIAL_FORMS": 0,
            "opt-0-media": str(img.pk), "opt-0-is_correct": "on", "opt-1-text": "Mask B", "opt-1-is_correct": "on", "opt-2-text": "Mask C",
        })
        multi = test.questions.get(prompt="Which masks are correct?")
        self.assertEqual(multi.options.filter(is_correct=True).count(), 2)
        self.assertEqual(multi.options.get(media=img).text, "")
        # edit: remove option B
        b = multi.options.get(text="Mask B")
        c = multi.options.get(text="Mask C")
        a = multi.options.get(media=img)
        self.post(self.trainer, "question_edit", multi.pk, data={
            "q-qtype": QuestionType.MULTI_SELECT, "q-prompt": "Which masks are correct?", "q-points": 3,
            "opt-TOTAL_FORMS": 3, "opt-INITIAL_FORMS": 3,
            "opt-0-id": a.pk, "opt-0-media": str(img.pk), "opt-0-is_correct": "on",
            "opt-1-id": b.pk, "opt-1-text": "Mask B", "opt-1-DELETE": "on",
            "opt-2-id": c.pk, "opt-2-text": "Mask C", "opt-2-is_correct": "on",
        })
        multi.refresh_from_db()
        self.assertEqual(multi.points, 3)
        self.assertEqual(set(multi.options.values_list("pk", flat=True)), {a.pk, c.pk})
        # reorder + publish with assignment to the project
        self.post(self.trainer, "question_move", tf.pk, data={"direction": "up"})
        self.assertEqual(list(test.questions.order_by("order").values_list("prompt", flat=True))[:2], ["Sky is blue", "Pick A"])
        self.post(self.trainer, "test_publish", test.pk, data={"assign": "1"})
        test.refresh_from_db()
        self.assertEqual(test.status, ContentStatus.PUBLISHED)
        self.assertEqual(TestAssignment.objects.filter(test=test).count(), 2)

    def test_question_move_reorders(self):
        q1 = self.test1.questions.get()
        q2 = Question.objects.create(test=self.test1, prompt="Second", order=5)
        self.post(self.trainer, "question_move", q2.pk, data={"direction": "up"})
        self.assertEqual(list(self.test1.questions.order_by("order").values_list("pk", flat=True)), [q2.pk, q1.pk])

    def test_results_and_csv(self):
        Test.objects.filter(pk=self.test1.pk).update(status=ContentStatus.PUBLISHED)
        self.test1.refresh_from_db()
        attempt = start_attempt(self.emp1, self.test1)
        submit_attempt(attempt, {str(self.q_ok.question_id): [self.q_ok.pk]})
        response = self.get(self.pm, "test_results", self.test1.pk)
        self.assertEqual(response.context["summary"]["passed"], 1)
        csv = self.get(self.pm, "test_results", self.test1.pk, format="csv")
        lines = csv.content.decode("utf-8-sig").splitlines()
        self.assertTrue(lines[0].startswith("Employee,Employee ID,Email,Status,Best score"))
        self.assertIn("Passed", lines[1])
        attempts_csv = self.get(self.pm, "test_results", self.test1.pk, format="csv", rows="attempts")
        self.assertIn("Attempt", attempts_csv.content.decode("utf-8-sig").splitlines()[0])
        detail = self.get(self.pm, "attempt_detail", attempt.pk)
        self.assertContains(detail, "Chosen · correct")
        # attempt by someone outside the PM's scope is hidden
        other_attempt = TestAttempt.objects.create(test=self.test1, user=self.other, attempt_number=1)
        self.assertEqual(self.get(self.pm, "attempt_detail", other_attempt.pk).status_code, 404)

    def test_onboarding_template_and_steps(self):
        self.post(self.trainer, "onboarding_template", self.p1.pk)
        steps = list(OnboardingStep.objects.filter(project=self.p1).order_by("order"))
        self.assertEqual(len(steps), 8)
        self.assertEqual(steps[0].title, "স্বাগতম ও প্রজেক্ট পরিচিতি")  # employees read the steps in Bangla
        self.assertEqual(steps[-1].step_type, "qualification")
        self.post(self.trainer, "step_move", steps[1].pk, data={"direction": "up"})
        self.assertEqual(OnboardingStep.objects.filter(project=self.p1).order_by("order").first().pk, steps[1].pk)
        self.post(self.trainer, "step_delete", steps[2].pk)
        self.assertEqual(list(OnboardingStep.objects.filter(project=self.p1).values_list("order", flat=True).order_by("order")), list(range(1, 8)))
        self.assertEqual(self.post(self.trainer, "onboarding_template", self.p2.pk).status_code, 404)

    def test_team_and_guideline_crud(self):
        self.post(self.pm, "project_teams", self.p1.pk, data={"name": "Team B", "lead": self.emp2.pk})
        team = Team.objects.get(project=self.p1, name="Team B")
        self.assertEqual(team.lead, self.emp2)
        self.post(self.pm, "team_update", team.pk, data={f"t{team.pk}-name": "Team Bravo", f"t{team.pk}-lead": ""})
        team.refresh_from_db()
        self.assertEqual(team.name, "Team Bravo")
        self.post(self.pm, "guideline_create", self.p1.pk, data={"title": "Rules", "version": "1.0", "order": 1, "content": "# Rules"})
        g = self.p1.guidelines.get(title="Rules")
        self.post(self.pm, "guideline_delete", g.pk)
        self.assertFalse(self.p1.guidelines.exists())
        self.post(self.pm, "team_delete", team.pk)
        self.assertFalse(Team.objects.filter(pk=team.pk).exists())

    def test_training_progress_and_reports(self):
        TutorialProgress.objects.filter(user=self.emp1, tutorial=self.tut1).update(status=ProgressStatus.COMPLETED, completed_at=timezone.now())
        response = self.get(self.pm, "training_progress", project=self.p1.pk)
        rows = {r["user"].pk: r for r in response.context["matrix"]}
        self.assertEqual((rows[self.emp1.pk]["done"], rows[self.emp1.pk]["assigned"]), (1, 1))
        self.assertEqual(rows[self.emp2.pk]["done"], 0)
        report = self.get(self.pm, "reports", format="csv")
        lines = report.content.decode("utf-8-sig").splitlines()
        self.assertTrue(lines[0].startswith("Employee,Employee ID,Email,Status,Projects,Training completion %"))
        self.assertTrue(any(self.emp1.email in line and ",100," in line for line in lines))
        self.assertFalse(any(self.other.email in line for line in lines))


class CommsAndSettingsTests(AdminTestCase):
    def test_announcement_notifies_project(self):
        self.post(self.pm, "announcement_create", data={"title": "Hello P1", "body": "News", "project": self.p1.pk, "priority": "normal", "send_email": "on"})
        a = Announcement.objects.get(title="Hello P1")
        self.assertEqual(set(Notification.objects.filter(title="Hello P1").values_list("user_id", flat=True)), {self.emp1.pk, self.emp2.pk})
        self.assertEqual(EmailMessage.objects.filter(template="announcement").count(), 2)
        # PM can't post company-wide
        self.post(self.pm, "announcement_create", data={"title": "Everyone", "body": "x", "project": "", "priority": "normal"})
        self.assertFalse(Announcement.objects.filter(title="Everyone").exists())
        self.post(self.admin, "announcement_create", data={"title": "Everyone", "body": "x", "project": "", "priority": "normal"})
        self.assertEqual(Notification.objects.filter(title="Everyone").count(), 4)  # all active employees
        self.post(self.pm, "announcement_delete", a.pk)
        self.assertFalse(Announcement.objects.filter(pk=a.pk).exists())

    def test_meeting_invites(self):
        start = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.post(self.pm, "meeting_create", data={
            "title": "Calibration", "starts_at": start, "duration_min": 30, "project": self.p1.pk,
            "meeting_url": "https://meet.google.com/abc", "audience": "project",
        })
        m = Meeting.objects.get(title="Calibration")
        self.assertEqual(set(m.invites.values_list("user_id", flat=True)), {self.emp1.pk, self.emp2.pk})
        self.assertEqual(EmailMessage.objects.filter(template="meeting_invite").count(), 2)
        self.post(self.pm, "meeting_edit", m.pk, data={
            "title": "Calibration", "starts_at": start, "duration_min": 45, "project": self.p1.pk,
            "meeting_url": "https://meet.google.com/abc", "audience": "selected", "invitees": [self.emp1.pk],
        })
        self.assertEqual(list(m.invites.values_list("user_id", flat=True)), [self.emp1.pk])
        self.post(self.pm, "meeting_cancel", m.pk)
        self.assertFalse(Meeting.objects.filter(pk=m.pk).exists())
        self.assertTrue(Notification.objects.filter(user=self.emp1, title="মিটিং বাতিল: Calibration").exists())

    def test_settings_save(self):
        data = {"form": "company", "company-email": "info@skyleon.example", "company-careers_email": "", "company-phone": "+1 555",
                "company-business_hours": "24/7", "company-linkedin": "https://linkedin.com/company/x", "company-show_map": "on",
                "company-map_embed_url": "https://www.google.com/maps/embed?pb=1"}
        self.post(self.admin, "settings", data=data)
        company = site_settings.company()
        self.assertEqual(company["email"], "info@skyleon.example")
        self.assertTrue(company["show_map"])
        self.assertEqual(set(company), set(site_settings.DEFAULT_COMPANY))
        self.post(self.admin, "settings", data={"form": "notifications", "notif-admin_emails": "a@x.test, b@x.test\na@x.test"})
        self.assertEqual(site_settings.notification_settings()["admin_emails"], ["a@x.test", "b@x.test"])
        self.post(self.admin, "settings", data={"form": "notifications", "notif-admin_emails": "not-an-email"})
        self.assertEqual(site_settings.notification_settings()["admin_emails"], ["a@x.test", "b@x.test"])

    def test_email_log_and_retry(self):
        e = EmailMessage.objects.create(to="x@x.test", subject="Hi", html="<p>Hi <script>alert(1)</script></p>", text="Hi",
                                        template="t", status=EmailStatus.FAILED, attempts=5)
        page = self.get(self.admin, "email_detail", e.pk)
        self.assertContains(page, 'sandbox=""')
        self.assertNotContains(page, "<script>alert(1)</script>")  # escaped inside srcdoc
        self.post(self.admin, "email_retry", data={"pk": e.pk})
        e.refresh_from_db()
        self.assertEqual(e.status, EmailStatus.SENT)

    def test_category_permissions(self):
        self.post(self.pm, "category_list", data={"name": "PM category", "order": 1})
        self.assertFalse(TutorialCategory.objects.filter(name="PM category").exists())
        self.post(self.trainer, "category_list", data={"name": "Trainer category", "order": 1})
        self.assertTrue(TutorialCategory.objects.filter(name="Trainer category", slug="trainer-category").exists())


class MediaScopeTests(AdminTestCase):
    """Files are only reachable / attachable through objects in the viewer's scope."""

    def _asset(self, kind=MediaKind.VIDEO, **extra):
        return MediaAsset.objects.create(kind=kind, provider="local", storage_key=f"x/{kind}.bin", status=MediaStatus.READY,
                                         original_name=f"{kind}.bin", **extra)

    def preview(self, user, asset):
        self.client.force_login(user)
        return self.client.get(reverse("storage:preview", args=[asset.pk]))

    def test_preview_checks_the_parent_object(self):
        cv = self._asset(MediaKind.DOCUMENT)
        JobApplication.objects.filter(pk=self.application.pk).update(cv=cv)
        quote_file = self._asset(MediaKind.DOCUMENT)
        QuoteRequest.objects.filter(pk=self.quote.pk).update(attachment=quote_file)
        p2_video = self._asset()
        Tutorial.objects.filter(pk=self.tut2.pk).update(video=p2_video)
        p1_video = self._asset()
        Tutorial.objects.filter(pk=self.tut1.pk).update(video=p1_video)
        thumb = self._asset(MediaKind.IMAGE)
        MediaAsset.objects.filter(pk=p1_video.pk).update(thumbnail=thumb)
        orphan = self._asset(uploaded_by=self.pm)

        # Applicant CVs: applicants.manage only (PM yes, trainer no)
        self.assertEqual(self.preview(self.trainer, cv).status_code, 404)
        self.assertEqual(self.preview(self.pm, cv).status_code, 302)
        # Quote attachments: leads.manage (super admin only)
        self.assertEqual(self.preview(self.pm, quote_file).status_code, 404)
        self.assertEqual(self.preview(self.admin, quote_file).status_code, 302)
        # Training content: only the viewer's projects (+ the thumbnails of those videos)
        self.assertEqual(self.preview(self.trainer, p2_video).status_code, 404)
        self.assertEqual(self.preview(self.trainer, p1_video).status_code, 302)
        self.assertEqual(self.preview(self.trainer, thumb).status_code, 302)
        # Unattached uploads: only the uploader (and super admins)
        self.assertEqual(self.preview(self.trainer, orphan).status_code, 404)
        self.assertEqual(self.preview(self.pm, orphan).status_code, 302)
        self.assertEqual(self.preview(self.admin, p2_video).status_code, 302)

    def test_asset_field_only_accepts_reachable_files(self):
        p2_video = self._asset()
        Tutorial.objects.filter(pk=self.tut2.pk).update(video=p2_video)
        foreign = self._asset(uploaded_by=self.pm)  # someone else's unattached upload
        cv = self._asset(MediaKind.VIDEO)
        JobApplication.objects.filter(pk=self.application.pk).update(cv=cv)
        data = {"title": "T", "project": self.p1.pk, "cadence": "daily"}
        for asset in (p2_video, foreign, cv):
            response = self.post(self.trainer, "tutorial_create", data={**data, "video": str(asset.pk)})
            self.assertEqual(response.status_code, 200, asset)
            self.assertFalse(Tutorial.objects.filter(title="T").exists())
            # the rejected id is neither echoed back nor turned into a signed URL
            self.assertNotContains(response, str(asset.pk))
        # files of content in scope and own uploads are fine
        own = self._asset(uploaded_by=self.trainer)
        self.post(self.trainer, "tutorial_create", data={**data, "title": "Own", "video": str(own.pk)})
        self.assertEqual(Tutorial.objects.get(title="Own").video, own)
        self.post(self.trainer, "tutorial_create", data={**data, "title": "Reuse", "video": str(self.video.pk)})
        self.assertEqual(Tutorial.objects.get(title="Reuse").video, self.video)
        # the saved value stays valid on edit even though the editor didn't upload it
        admin_upload = self._asset(uploaded_by=self.admin)
        Tutorial.objects.filter(pk=self.tut1.pk).update(video=admin_upload)
        response = self.post(self.trainer, "tutorial_edit", self.tut1.pk, data={**data, "title": "P1 renamed", "video": str(admin_upload.pk)})
        self.assertEqual(response.status_code, 302)
        self.tut1.refresh_from_db()
        self.assertEqual((self.tut1.title, self.tut1.video), ("P1 renamed", admin_upload))

    def test_guideline_document_cannot_reference_a_cv(self):
        cv = self._asset(MediaKind.DOCUMENT)
        JobApplication.objects.filter(pk=self.application.pk).update(cv=cv)
        response = self.post(self.admin, "guideline_create", self.p1.pk,
                             data={"title": "Rules", "version": "1.0", "order": 1, "content": "x", "document": str(cv.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.p1.guidelines.exists())


class ApplicantConversionTests(AdminTestCase):
    def test_new_account_gets_an_invite(self):
        response = self.post(self.pm, "applicant_convert", self.application.pk, data={})
        user = User.objects.get(email="applicant@x.test")
        self.assertRedirects(response, reverse("backoffice:employee_detail", args=[user.pk]), fetch_redirect_response=False)
        self.assertTrue(EmailMessage.objects.filter(to="applicant@x.test", template="account_invite").exists())

    def _apply_as(self, user):
        return JobApplication.objects.create(full_name=user.name, email=user.email.upper(), phone="1", location="Remote")

    def test_suspended_account_is_not_reactivated(self):
        self.emp2.status = UserStatus.SUSPENDED
        self.emp2.save()
        app = self._apply_as(self.emp2)
        page = self.get(self.pm, "applicant_detail", app.pk)
        self.assertContains(page, "An account with this email already exists (Employee · Suspended)")
        self.assertNotContains(page, reverse("backoffice:applicant_convert", args=[app.pk]))
        response = self.post(self.pm, "applicant_convert", app.pk)
        self.assertRedirects(response, reverse("backoffice:applicant_detail", args=[app.pk]), fetch_redirect_response=False)
        self.emp2.refresh_from_db()
        app.refresh_from_db()
        self.assertEqual(self.emp2.status, UserStatus.SUSPENDED)
        self.assertIsNone(app.user_id)
        self.assertFalse(EmailMessage.objects.filter(to=self.emp2.email, template__in=["account_invite", "account_approved"]).exists())

    def test_staff_account_is_never_attached(self):
        app = self._apply_as(self.trainer)
        self.post(self.admin, "applicant_convert", app.pk)
        app.refresh_from_db()
        self.trainer.refresh_from_db()
        self.assertIsNone(app.user_id)
        self.assertEqual((self.trainer.role, self.trainer.status), (Role.TRAINER, UserStatus.ACTIVE))

    def test_existing_employee_is_linked_unchanged_without_email(self):
        app = self._apply_as(self.pending)
        response = self.post(self.pm, "applicant_convert", app.pk)
        self.assertRedirects(response, reverse("backoffice:employee_detail", args=[self.pending.pk]), fetch_redirect_response=False)
        app.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual(app.user, self.pending)
        self.assertEqual(self.pending.status, UserStatus.PENDING)  # not approved behind the PM's back
        self.assertFalse(EmailMessage.objects.filter(to=self.pending.email, template__in=["account_invite", "account_approved"]).exists())
        text = " ".join(str(m) for m in response.wsgi_request._messages)
        self.assertIn("no email was sent", text)
        self.assertNotIn("has been sent", text)

    def test_link_hidden_when_viewer_cannot_see_the_account(self):
        app = self._apply_as(self.other)  # employee of P2 — outside the PM's people area
        page = self.get(self.pm, "applicant_detail", app.pk)
        self.assertContains(page, "An account with this email already exists (Employee · Active)")
        self.assertNotContains(page, reverse("backoffice:employee_detail", args=[self.other.pk]))
        response = self.post(self.pm, "applicant_convert", app.pk)
        self.assertRedirects(response, reverse("backoffice:applicant_detail", args=[app.pk]), fetch_redirect_response=False)


class ValidationTests(AdminTestCase):
    def test_non_finite_score_filter_is_ignored(self):
        for value in ("nan", "inf", "-inf", "1e999"):
            self.assertEqual(self.get(self.trainer, "feedback_tracking", score_min=value).status_code, 200, value)
            self.assertEqual(self.get(self.trainer, "feedback_detail", self.fb1.pk, score_max=value).status_code, 200, value)

    def test_pm_cannot_change_an_email(self):
        data = {"name": "Emp1", "email": "attacker@evil.test", "phone": "", "location": "", "title": "", "bio": ""}
        self.post(self.pm, "employee_edit", self.emp1.pk, data=data)
        self.emp1.refresh_from_db()
        self.assertEqual(self.emp1.email, "emp1@t.test")
        self.post(self.admin, "employee_edit", self.emp1.pk, data={**data, "email": "new-emp1@t.test"})
        self.emp1.refresh_from_db()
        self.assertEqual(self.emp1.email, "new-emp1@t.test")

    def test_role_change_feedback(self):
        response = self.post(self.admin, "employee_role", self.emp1.pk, data={"role": "wizard"})
        self.assertIn("Choose a valid role", " ".join(str(m) for m in response.wsgi_request._messages))
        response = self.post(self.admin, "employee_role", self.emp1.pk, data={"role": Role.EMPLOYEE})
        self.assertIn("nothing changed", " ".join(str(m) for m in response.wsgi_request._messages))

    def test_test_settings_limits(self):
        base = {"title": "Limits", "kind": TestKind.TRAINING, "project": self.p1.pk, "passing_score": 80}
        for extra in ({"attempt_limit": 0}, {"time_limit_min": 0}, {"passing_score": 0}):
            response = self.post(self.trainer, "test_create", data={**base, **extra})
            self.assertEqual(response.status_code, 200, extra)
        self.assertFalse(Test.objects.filter(title="Limits").exists())
        self.post(self.trainer, "test_create", data={**base, "attempt_limit": "", "time_limit_min": ""})
        test = Test.objects.get(title="Limits")
        self.assertIsNone(test.attempt_limit)  # empty = unlimited

    def test_question_needs_points(self):
        response = self.post(self.trainer, "question_create", self.test1.pk, data={
            "q-qtype": QuestionType.TRUE_FALSE, "q-prompt": "Zero", "q-points": 0, "q-tf_answer": "true",
            "opt-TOTAL_FORMS": 0, "opt-INITIAL_FORMS": 0,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Question.objects.filter(prompt="Zero").exists())

    def test_true_false_edit_keeps_existing_english_options(self):
        q = Question.objects.create(test=self.test1, prompt="Old TF", qtype=QuestionType.TRUE_FALSE)
        t = QuestionOption.objects.create(question=q, text="True", is_correct=True)
        f = QuestionOption.objects.create(question=q, text="False")
        self.post(self.trainer, "question_edit", q.pk, data={
            "q-qtype": QuestionType.TRUE_FALSE, "q-prompt": "Old TF", "q-points": 1, "q-tf_answer": "false",
            "opt-TOTAL_FORMS": 0, "opt-INITIAL_FORMS": 0,
        })
        self.assertEqual(list(q.options.values_list("pk", "text", "is_correct")), [(t.pk, "True", False), (f.pk, "False", True)])

    def test_meeting_validation(self):
        base = {"title": "M", "duration_min": 30, "project": self.p1.pk, "meeting_url": "https://meet.google.com/abc", "audience": "project"}
        future = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        past = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.assertEqual(self.post(self.pm, "meeting_create", data={**base, "starts_at": past}).status_code, 200)
        self.assertEqual(self.post(self.pm, "meeting_create", data={**base, "starts_at": future, "duration_min": 2}).status_code, 200)
        self.assertFalse(Meeting.objects.filter(title="M").exists())
        self.post(self.pm, "meeting_create", data={**base, "starts_at": future})
        self.assertTrue(Meeting.objects.filter(title="M").exists())

    def test_project_colour_and_organisation(self):
        from apps.accounts.models import Organization

        org = Organization.objects.create(name="Acme", slug="acme")
        data = {"name": "Project One", "code": "P1-01", "slug": "p1", "status": "active", "color": "#123456", "organization": org.pk}
        self.post(self.pm, "project_edit", self.p1.pk, data=data)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.color, "#123456")
        self.assertIsNone(self.p1.organization_id)  # PMs can't move a project to a client organisation
        response = self.post(self.pm, "project_edit", self.p1.pk, data={**data, "color": "red;background:url(x)"})
        self.assertEqual(response.status_code, 200)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.color, "#123456")
        self.post(self.admin, "project_edit", self.p1.pk, data=data)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.organization, org)

    def test_published_tutorial_keeps_its_video(self):
        data = {"title": "P1 tutorial", "project": self.p1.pk, "cadence": "daily", "video": ""}
        response = self.post(self.trainer, "tutorial_edit", self.tut1.pk, data=data)
        self.assertContains(response, "Unpublish first or choose another video")
        self.tut1.refresh_from_db()
        self.assertEqual(self.tut1.video, self.video)

    def test_published_feedback_keeps_its_audience(self):
        self.post(self.trainer, "feedback_publish", self.fb1.pk)
        other_team = Team.objects.create(project=self.p1, name="Team Z")
        self.post(self.admin, "feedback_edit", self.fb1.pk, data={
            "topic": "Changed", "explanation": "x", "project": self.p2.pk, "team": other_team.pk,
            "severity": "normal", "cadence": "daily", "then": "save",
        })
        self.fb1.refresh_from_db()
        self.assertEqual((self.fb1.topic, self.fb1.project, self.fb1.team), ("Changed", self.p1, None))

    def test_feedback_project_must_match_linked_test(self):
        self.post(self.trainer, "feedback_test_create", self.fb1.pk)
        response = self.post(self.admin, "feedback_edit", self.fb1.pk, data={
            "topic": "Boxes too loose", "explanation": "x", "project": self.p2.pk, "severity": "normal", "cadence": "daily", "then": "save",
        })
        self.assertEqual(response.status_code, 200)
        self.fb1.refresh_from_db()
        self.assertEqual(self.fb1.project, self.p1)
        test = self.fb1.test
        self.assertEqual(test.title, f"ফিডব্যাক {self.fb1.display_number} যাচাই — {self.fb1.topic}")


class DashboardConsistencyTests(AdminTestCase):
    def test_tiles_match_the_linked_pages(self):
        Feedback.objects.filter(pk=self.fb2.pk).update(status=ContentStatus.ARCHIVED)
        self.post(self.trainer, "feedback_publish", self.fb1.pk)
        FeedbackRecipient.objects.create(feedback=self.fb2, user=self.other)
        Test.objects.filter(pk=self.test1.pk).update(status=ContentStatus.PUBLISHED)
        TestAssignment.objects.create(test=self.test1, user=self.emp1)
        TestAssignment.objects.create(test=self.test1, user=self.emp2)
        for user in (self.admin, self.pm, self.trainer):
            tiles = {t["label"]: t for t in self.get(user, "dashboard").context["tiles"]}
            unseen = tiles["Unseen feedback"]
            self.assertEqual(unseen["query"], "?state=unseen")
            tracking = self.get(user, "feedback_tracking", state="unseen")
            self.assertEqual(unseen["value"], tracking.context["summary"]["total"], user.email)
            pending = tiles["Tests pending"]
            self.assertEqual(pending["query"], "?pending=1")
            self.assertEqual(pending["value"], self.get(user, "test_list", pending="1").context["pending_total"], user.email)
            if "Total employees" in tiles:
                self.assertIn("role=employee", tiles["Total employees"]["query"])
                listed = self.get(user, "employee_list", role="employee").context["page"].paginator.count
                self.assertEqual(tiles["Total employees"]["value"], listed, user.email)

    def test_dashboard_links_only_people_in_scope(self):
        Test.objects.filter(pk=self.test1.pk).update(status=ContentStatus.PUBLISHED)
        glob = Test.objects.create(title="Company test", status=ContentStatus.PUBLISHED)
        q = Question.objects.create(test=glob, prompt="?", qtype=QuestionType.SINGLE_CHOICE)
        ok = QuestionOption.objects.create(question=q, text="A", is_correct=True)
        QuestionOption.objects.create(question=q, text="B")
        attempt = start_attempt(self.other, glob)
        submit_attempt(attempt, {str(q.pk): [ok.pk]})
        html = self.get(self.trainer, "dashboard").content.decode()
        self.assertNotIn(reverse("backoffice:employee_detail", args=[self.other.pk]), html)
        self.assertIn(reverse("backoffice:employee_detail", args=[self.other.pk]), self.get(self.admin, "dashboard").content.decode())

    def test_members_tab_links_and_messages(self):
        html = self.get(self.pm, "project_members", self.p1.pk).content.decode()
        self.assertIn(reverse("backoffice:employee_detail", args=[self.emp1.pk]), html)
        self.assertNotIn(reverse("backoffice:employee_detail", args=[self.trainer.pk]), html)  # staff: outside a PM's people area
        response = self.post(self.pm, "project_members", self.p1.pk, data={"users": [self.other.pk], "role": MemberRole.ANNOTATOR})
        text = " ".join(str(m) for m in response.context["messages"])
        self.assertIn("can't be added", text)
        self.assertNotIn("Select at least one person", text)


    def test_meeting_invitees_link_only_when_visible(self):
        m = Meeting.objects.create(title="Sync", starts_at=timezone.now() + timedelta(days=1), project=self.p1, created_by=self.pm)
        MeetingInvite.objects.create(meeting=m, user=self.emp1)
        MeetingInvite.objects.create(meeting=m, user=self.trainer)
        html = self.get(self.pm, "meeting_detail", m.pk).content.decode()
        self.assertIn(reverse("backoffice:employee_detail", args=[self.emp1.pk]), html)
        self.assertNotIn(reverse("backoffice:employee_detail", args=[self.trainer.pk]), html)
        self.assertIn(self.trainer.name, html)


class QueryCountTests(AdminTestCase):
    def _queries(self, name, *args):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_login(self.pm)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse(f"backoffice:{name}", args=args))
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries), response

    def test_teams_page_does_not_query_per_team(self):
        Team.objects.filter(pk=self.team_a.pk).update(lead=self.emp1)
        one, response = self._queries("project_teams", self.p1.pk)
        self.assertContains(response, f'<option value="{self.emp1.pk}" selected>')
        for i in range(3):
            Team.objects.create(project=self.p1, name=f"Extra {i}")
        self.assertEqual(self._queries("project_teams", self.p1.pk)[0], one)

    def test_tutorial_list_does_not_query_per_row(self):
        one = self._queries("tutorial_list")[0]
        for i in range(3):
            Tutorial.objects.create(title=f"Extra {i}", project=self.p1)
        self.assertEqual(self._queries("tutorial_list")[0], one)


class ExportAuditTests(AdminTestCase):
    def test_csv_exports_are_audited(self):
        self.get(self.admin, "message_list", format="csv")
        self.get(self.pm, "reports", format="csv")
        self.assertTrue(AuditLog.objects.filter(action="messages.export").exists())
        self.assertTrue(AuditLog.objects.filter(action="reports.export").exists())
