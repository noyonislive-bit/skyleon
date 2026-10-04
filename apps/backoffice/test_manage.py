"""
Admin panel: managing everything from the browser — organisations & client accounts, deleting users,
assignment adjustments (unassign, due dates, test attempts), project deletion, website enquiries and
company-wide onboarding.

    DB_TEST_NAME=test_skyleon_manage python manage.py test apps.backoffice.test_manage
"""

import re

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Organization, Role, User, UserStatus
from apps.accounts.services import deletion_problem
from apps.assessments.models import Test, TestAssignment, TestAttempt
from apps.assessments.services import start_attempt, submit_attempt, test_state
from apps.comms.models import EmailMessage, Notification
from apps.core.choices import ContentStatus, ProgressStatus
from apps.core.models import AuditLog
from apps.feedback.models import Feedback, FeedbackRecipient
from apps.feedback.services import publish_feedback
from apps.training.models import TutorialProgress
from apps.website.models import JobApplication

from .tests import AdminTestCase


def audited(action, **filters):
    return AuditLog.objects.filter(action=action, **filters).exists()


class OrganizationTests(AdminTestCase):
    def test_only_super_admins_manage_clients(self):
        org = Organization.objects.create(name="Acme", slug="acme")
        for name, args in (("organization_list", ()), ("organization_create", ()), ("organization_detail", (org.pk,)),
                           ("organization_edit", (org.pk,)), ("client_create", (org.pk,))):
            self.assertEqual(self.get(self.admin, name, *args).status_code, 200, name)
            self.assertEqual(self.get(self.pm, name, *args).status_code, 403, name)
            self.assertEqual(self.get(self.trainer, name, *args).status_code, 403, name)
        self.assertIn(reverse("backoffice:organization_list"), self.get(self.admin, "dashboard").content.decode())
        self.assertNotIn(reverse("backoffice:organization_list"), self.get(self.pm, "dashboard").content.decode())

    def test_create_edit_and_list_organisation(self):
        response = self.post(self.admin, "organization_create", data={"name": "  Northwind   Traders ", "slug": "", "contact_email": "ops@nw.test"})
        org = Organization.objects.get(name="Northwind Traders")
        self.assertRedirects(response, reverse("backoffice:organization_detail", args=[org.pk]), fetch_redirect_response=False)
        self.assertEqual(org.slug, "northwind-traders")
        self.assertTrue(audited("organization.create", entity_id=str(org.pk)))
        # same name again → a unique slug is generated; a typed duplicate slug is refused
        self.post(self.admin, "organization_create", data={"name": "Northwind Traders", "slug": ""})
        self.assertTrue(Organization.objects.filter(slug="northwind-traders-2").exists())
        response = self.post(self.admin, "organization_create", data={"name": "Other", "slug": "northwind-traders"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Organization.objects.filter(name="Other").exists())

        self.post(self.admin, "organization_edit", org.pk, data={"name": "Northwind", "slug": "northwind", "contact_email": ""})
        org.refresh_from_db()
        self.assertEqual((org.name, org.slug, org.contact_email), ("Northwind", "northwind", ""))
        self.assertContains(self.get(self.admin, "organization_list"), "Northwind")
        self.assertContains(self.get(self.admin, "organization_list", q="nw.test"), "No organisations yet")

    def test_add_client_account_with_invite(self):
        org = Organization.objects.create(name="Acme", slug="acme")
        response = self.post(self.admin, "client_create", org.pk, data={
            "name": "Clara Client", "email": "Clara@Acme.test", "title": "Head of data", "send_invite": "on",
        })
        self.assertRedirects(response, reverse("backoffice:organization_detail", args=[org.pk]), fetch_redirect_response=False)
        client = User.objects.get(email="clara@acme.test")
        self.assertEqual((client.role, client.status, client.organization), (Role.CLIENT, UserStatus.ACTIVE, org))
        self.assertIsNone(client.employee_id)
        self.assertFalse(client.has_usable_password())
        mail = EmailMessage.objects.get(to="clara@acme.test")
        self.assertEqual(mail.template, "client_invite")  # English, with the client sign-in page
        self.assertIn(reverse("accounts:client_login"), mail.text)
        self.assertTrue(audited("client.create", entity_id=str(client.pk)))
        # duplicate email refused
        response = self.post(self.admin, "client_create", org.pk, data={"name": "Again", "email": "clara@acme.test"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(email="clara@acme.test").count(), 1)
        detail = self.get(self.admin, "organization_detail", org.pk)
        self.assertContains(detail, "Clara Client")

        # the invite link leads to an English set-password page and then to the client login
        setup_url = re.search(r"(/password/set/[^\s]+/)", mail.text).group(1)
        browser = Client()
        page = browser.get(setup_url, follow=True)
        self.assertContains(page, "Choose a password")
        response = browser.post(page.redirect_chain[-1][0] if page.redirect_chain else setup_url,
                                {"new_password1": "Very-Long-pass-42", "new_password2": "Very-Long-pass-42"})
        self.assertRedirects(response, reverse("accounts:password_reset_complete") + "?for=client", fetch_redirect_response=False)
        done = browser.get(response["Location"])
        self.assertContains(done, reverse("accounts:client_login"))
        client.refresh_from_db()
        self.assertTrue(client.check_password("Very-Long-pass-42"))

    def test_client_portal_shows_the_organisation_projects(self):
        org = Organization.objects.create(name="Acme", slug="acme")
        User.objects.filter(pk=self.client_user.pk).update(organization=org)
        self.post(self.admin, "organization_projects", org.pk, data={"action": "link", "project": self.p1.pk})
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.organization, org)
        self.client.force_login(self.client_user)
        page = self.client.get(reverse("clients:dashboard"))
        self.assertContains(page, self.p1.name)
        self.assertNotContains(page, self.p2.name)
        self.post(self.admin, "organization_projects", org.pk, data={"action": "unlink", "project": self.p1.pk})
        self.p1.refresh_from_db()
        self.assertIsNone(self.p1.organization)
        self.client.force_login(self.client_user)
        self.assertNotContains(self.client.get(reverse("clients:dashboard")), self.p1.name)

    def test_move_client_to_another_organisation(self):
        acme = Organization.objects.create(name="Acme", slug="acme")
        globex = Organization.objects.create(name="Globex", slug="globex")
        User.objects.filter(pk=self.client_user.pk).update(organization=acme)
        self.assertContains(self.get(self.admin, "organization_detail", acme.pk), self.client_user.email)
        response = self.post(self.admin, "client_edit", self.client_user.pk, data={
            "name": "Client Person", "email": self.client_user.email, "title": "", "phone": "", "organization": globex.pk,
        })
        self.assertRedirects(response, reverse("backoffice:organization_detail", args=[globex.pk]), fetch_redirect_response=False)
        self.client_user.refresh_from_db()
        self.assertEqual((self.client_user.name, self.client_user.organization), ("Client Person", globex))
        self.assertTrue(audited("client.edit", entity_id=str(self.client_user.pk)))
        # only client accounts are edited here
        self.assertEqual(self.get(self.admin, "client_edit", self.emp1.pk).status_code, 404)
        # the employee page of a client points to its organisation
        self.assertContains(self.get(self.admin, "employee_detail", self.client_user.pk),
                            reverse("backoffice:organization_detail", args=[globex.pk]))

    def test_unattached_clients_are_listed(self):
        page = self.get(self.admin, "organization_list")
        self.assertContains(page, "Client accounts without an organisation")
        self.assertContains(page, reverse("backoffice:client_edit", args=[self.client_user.pk]))

    def test_delete_only_empty_organisations(self):
        org = Organization.objects.create(name="Acme", slug="acme")
        User.objects.filter(pk=self.client_user.pk).update(organization=org)
        self.p1.organization = org
        self.p1.save()
        response = self.post(self.admin, "organization_delete", org.pk)
        self.assertRedirects(response, reverse("backoffice:organization_detail", args=[org.pk]), fetch_redirect_response=False)
        self.assertTrue(Organization.objects.filter(pk=org.pk).exists())
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any("1 account and 1 project" in m for m in messages), messages)
        self.assertEqual(self.post(self.pm, "organization_delete", org.pk).status_code, 403)

        User.objects.filter(pk=self.client_user.pk).update(organization=None)
        self.post(self.admin, "organization_projects", org.pk, data={"action": "unlink", "project": self.p1.pk})
        response = self.post(self.admin, "organization_delete", org.pk)
        self.assertRedirects(response, reverse("backoffice:organization_list"), fetch_redirect_response=False)
        self.assertFalse(Organization.objects.filter(pk=org.pk).exists())
        self.assertTrue(audited("organization.delete", entity_id=str(org.pk)))

    def test_client_password_link_and_suspend(self):
        org = Organization.objects.create(name="Acme", slug="acme")
        User.objects.filter(pk=self.client_user.pk).update(organization=org)
        back = reverse("backoffice:organization_detail", args=[org.pk])
        response = self.post(self.admin, "employee_invite", self.client_user.pk, data={"next": back})
        self.assertRedirects(response, back, fetch_redirect_response=False)
        self.assertTrue(EmailMessage.objects.filter(to=self.client_user.email, template="client_invite").exists())
        self.post(self.admin, "employee_status", self.client_user.pk, data={"action": "suspend", "next": back})
        self.client_user.refresh_from_db()
        self.assertEqual(self.client_user.status, UserStatus.SUSPENDED)
        # employees still get the Bangla invite
        self.post(self.admin, "employee_invite", self.emp1.pk)
        self.assertTrue(EmailMessage.objects.filter(to=self.emp1.email, template="account_invite").exists())


class UserDeletionTests(AdminTestCase):
    def test_super_admin_deletes_an_account(self):
        TestAttempt.objects.create(test=self.test1, user=self.emp2, attempt_number=1)
        JobApplication.objects.filter(pk=self.application.pk).update(user=self.emp2)
        page = self.get(self.admin, "employee_delete", self.emp2.pk)
        self.assertContains(page, "Delete account permanently")
        self.assertContains(page, "1 test attempt")
        self.assertContains(page, "1 project membership")
        response = self.post(self.admin, "employee_delete", self.emp2.pk)
        self.assertRedirects(response, reverse("backoffice:employee_list"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.emp2.pk).exists())
        self.assertFalse(TestAttempt.objects.filter(user_id=self.emp2.pk).exists())
        self.application.refresh_from_db()
        self.assertIsNone(self.application.user)  # the careers application is kept
        log = AuditLog.objects.get(action="employee.delete", entity_id=str(self.emp2.pk))
        self.assertEqual(log.meta["email"], "emp2@t.test")

    def test_only_super_admins_and_never_yourself(self):
        self.assertEqual(self.get(self.pm, "employee_delete", self.emp2.pk).status_code, 403)
        self.assertEqual(self.post(self.pm, "employee_delete", self.emp2.pk).status_code, 403)
        page = self.get(self.admin, "employee_delete", self.admin.pk)
        self.assertContains(page, "You cannot delete your own account.")
        self.assertNotContains(page, "Delete account permanently")
        self.post(self.admin, "employee_delete", self.admin.pk)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertNotContains(self.get(self.admin, "employee_detail", self.admin.pk),
                               reverse("backoffice:employee_delete", args=[self.admin.pk]))
        self.assertContains(self.get(self.admin, "employee_detail", self.emp1.pk),
                            reverse("backoffice:employee_delete", args=[self.emp1.pk]))

    def test_last_active_super_admin_is_protected(self):
        other_admin = User.objects.create_user(email="admin2@t.test", password="x", name="Admin Two",
                                               role=Role.SUPER_ADMIN, status=UserStatus.ACTIVE)
        self.assertIsNone(deletion_problem(other_admin, self.admin))
        User.objects.filter(pk=other_admin.pk).update(status=UserStatus.SUSPENDED)
        self.assertIn("last active super admin", deletion_problem(other_admin, self.admin))
        # with two active super admins, one may delete the other
        User.objects.filter(pk=other_admin.pk).update(status=UserStatus.ACTIVE)
        self.post(self.admin, "employee_delete", other_admin.pk)
        self.assertFalse(User.objects.filter(pk=other_admin.pk).exists())

    def test_delete_client_returns_to_its_organisation(self):
        org = Organization.objects.create(name="Acme", slug="acme")
        User.objects.filter(pk=self.client_user.pk).update(organization=org)
        back = reverse("backoffice:organization_detail", args=[org.pk])
        page = self.get(self.admin, "employee_delete", self.client_user.pk, next=back)
        self.assertContains(page, f'name="next" value="{back}"')
        response = self.post(self.admin, "employee_delete", self.client_user.pk, data={"next": back})
        self.assertRedirects(response, back, fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.client_user.pk).exists())

    def test_reject_pending_signup(self):
        self.assertContains(self.get(self.admin, "employee_list", status="pending"),
                            reverse("backoffice:employee_reject", args=[self.pending.pk]))
        self.assertEqual(self.post(self.pm, "employee_reject", self.pending.pk).status_code, 403)
        response = self.post(self.admin, "employee_reject", self.pending.pk)
        self.assertRedirects(response, reverse("backoffice:employee_list") + "?status=pending", fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.pending.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="employee.reject", meta__email="pending@t.test").exists())

    def test_reject_only_pending_accounts(self):
        self.post(self.admin, "employee_reject", self.emp1.pk)
        self.assertTrue(User.objects.filter(pk=self.emp1.pk).exists())


class AssignmentAdjustmentTests(AdminTestCase):
    def publish_test(self, limit=None):
        Test.objects.filter(pk=self.test1.pk).update(status=ContentStatus.PUBLISHED, attempt_limit=limit)
        self.test1.refresh_from_db()

    def fail_once(self, user):
        attempt = start_attempt(user, self.test1)
        return submit_attempt(attempt, {})  # no answer → 0 %

    # ── Tutorials ──────────────────────────────────────────────────────────
    def test_tutorial_due_date_and_unassign(self):
        row = TutorialProgress.objects.get(user=self.emp1, tutorial=self.tut1)
        self.post(self.trainer, "progress_due", row.pk, data={"due_date": "2031-03-15"})
        row.refresh_from_db()
        self.assertEqual(timezone.localtime(row.due_at).date().isoformat(), "2031-03-15")
        self.assertTrue(audited("tutorial.due_date", entity_id=str(self.tut1.pk)))
        self.post(self.trainer, "progress_due", row.pk, data={"due_date": ""})  # empty clears it
        row.refresh_from_db()
        self.assertIsNone(row.due_at)
        self.post(self.trainer, "progress_due", row.pk, data={"due_date": "not-a-date"})
        row.refresh_from_db()
        self.assertIsNone(row.due_at)

        # never opened → the row is removed
        response = self.post(self.trainer, "progress_unassign", row.pk)
        self.assertRedirects(response, reverse("backoffice:employee_detail", args=[self.emp1.pk]) + "?tab=tutorials",
                             fetch_redirect_response=False)
        self.assertFalse(TutorialProgress.objects.filter(pk=row.pk).exists())
        self.assertTrue(audited("tutorial.unassign", entity_id=str(self.tut1.pk)))

    def test_unassign_keeps_watch_history(self):
        row = TutorialProgress.objects.get(user=self.emp2, tutorial=self.tut1)
        TutorialProgress.objects.filter(pk=row.pk).update(first_viewed_at=timezone.now(), watched_seconds=12, percent=40,
                                                          status=ProgressStatus.IN_PROGRESS)
        self.post(self.pm, "progress_unassign", row.pk)
        row.refresh_from_db()
        self.assertFalse(row.assigned)
        self.assertEqual(row.watched_seconds, 12)

    def test_assignment_actions_are_scoped(self):
        p2_row = TutorialProgress.objects.get(user=self.other, tutorial=self.tut2)
        self.assertEqual(self.post(self.pm, "progress_unassign", p2_row.pk).status_code, 403)
        self.assertEqual(self.post(self.emp1, "progress_unassign", p2_row.pk).status_code, 403)
        self.assertEqual(self.client.get(reverse("backoffice:progress_unassign", args=[p2_row.pk])).status_code, 405)
        self.assertTrue(TutorialProgress.objects.filter(pk=p2_row.pk).exists())

    # ── Tests ──────────────────────────────────────────────────────────────
    def test_test_due_date_and_unassign(self):
        self.publish_test()
        assignment = TestAssignment.objects.create(test=self.test1, user=self.emp1)
        self.post(self.trainer, "test_assignment_due", assignment.pk, data={"due_date": "2031-01-02"})
        assignment.refresh_from_db()
        self.assertEqual(timezone.localtime(assignment.due_at).date().isoformat(), "2031-01-02")
        self.fail_once(self.emp1)
        self.post(self.trainer, "test_assignment_unassign", assignment.pk)
        self.assertFalse(TestAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertEqual(TestAttempt.objects.filter(test=self.test1, user=self.emp1).count(), 1)  # history kept
        self.assertTrue(audited("test.unassign", entity_id=str(self.test1.pk)))

    def test_extra_attempt_unlocks_a_locked_test(self):
        self.publish_test(limit=1)
        self.fail_once(self.emp1)
        state = test_state(self.emp1, self.test1)
        self.assertEqual((state.status, state.attempts_left, state.attempt_limit), ("locked", 0, 1))

        self.post(self.trainer, "test_extra_attempt", self.test1.pk, self.emp1.pk)
        assignment = TestAssignment.objects.get(test=self.test1, user=self.emp1)
        self.assertEqual(assignment.extra_attempts, 1)
        state = test_state(self.emp1, self.test1)
        self.assertEqual((state.status, state.attempts_left, state.attempt_limit), ("review", 1, 2))
        self.assertTrue(Notification.objects.filter(user=self.emp1, title__contains=self.test1.title).exists())
        self.assertTrue(audited("test.extra_attempt", entity_id=str(self.test1.pk)))

        # the employee portal now offers the retake and shows the new limit
        self.client.force_login(self.emp1)
        page = self.client.get(reverse("portal:test_detail", args=[self.test1.pk]))
        self.assertContains(page, "আর 1টি চেষ্টা বাকি")
        self.assertContains(page, "/2")
        self.assertEqual(self.client.get(reverse("portal:tests")).status_code, 200)
        attempt = start_attempt(self.emp1, self.test1)
        self.assertEqual(attempt.attempt_number, 2)

        # results page shows the effective limit
        results = self.get(self.trainer, "test_results", self.test1.pk)
        self.assertContains(results, "incl. 1 extra")

    def test_open_tests_count_honours_extra_attempts(self):
        from apps.portal.scope import PortalScope

        self.publish_test(limit=1)
        self.fail_once(self.emp1)
        self.assertFalse(PortalScope(self.emp1).open_tests().filter(pk=self.test1.pk).exists())
        self.post(self.trainer, "test_extra_attempt", self.test1.pk, self.emp1.pk)
        self.assertTrue(PortalScope(self.emp1).open_tests().filter(pk=self.test1.pk).exists())

    def test_extra_attempt_not_needed_for_unlimited_tests(self):
        self.publish_test(limit=None)
        self.post(self.trainer, "test_extra_attempt", self.test1.pk, self.emp1.pk)
        self.assertFalse(TestAssignment.objects.filter(test=self.test1, user=self.emp1, extra_attempts__gt=0).exists())

    def test_reset_attempts(self):
        self.publish_test(limit=1)
        self.fail_once(self.emp1)
        self.post(self.trainer, "test_extra_attempt", self.test1.pk, self.emp1.pk)
        response = self.post(self.trainer, "test_reset_attempts", self.test1.pk, self.emp1.pk,
                             data={"next": reverse("backoffice:test_results", args=[self.test1.pk])})
        self.assertRedirects(response, reverse("backoffice:test_results", args=[self.test1.pk]), fetch_redirect_response=False)
        self.assertFalse(TestAttempt.objects.filter(test=self.test1, user=self.emp1).exists())
        self.assertEqual(TestAssignment.objects.get(test=self.test1, user=self.emp1).extra_attempts, 0)
        state = test_state(self.emp1, self.test1)
        self.assertEqual((state.status, state.attempts_left), ("pending", 1))
        self.assertTrue(audited("test.reset_attempts", entity_id=str(self.test1.pk)))

    def test_attempt_actions_need_scope(self):
        self.publish_test(limit=1)
        TestAttempt.objects.create(test=self.test1, user=self.other, attempt_number=1, submitted_at=timezone.now(), score=0, passed=False)
        # `other` is not in the PM's people scope; test2 is not in the trainer's projects
        self.assertEqual(self.post(self.pm, "test_reset_attempts", self.test1.pk, self.other.pk).status_code, 404)
        self.assertEqual(self.post(self.trainer, "test_extra_attempt", self.test2.pk, self.emp1.pk).status_code, 404)
        self.assertEqual(self.post(self.emp1, "test_reset_attempts", self.test1.pk, self.emp1.pk).status_code, 403)
        self.assertTrue(TestAttempt.objects.filter(test=self.test1, user=self.other).exists())

    def test_employee_page_shows_the_actions(self):
        self.publish_test(limit=2)
        TestAssignment.objects.create(test=self.test1, user=self.emp1, extra_attempts=1)
        self.fail_once(self.emp1)
        page = self.get(self.trainer, "employee_detail", self.emp1.pk, tab="tests")
        self.assertContains(page, reverse("backoffice:test_reset_attempts", args=[self.test1.pk, self.emp1.pk]))
        self.assertContains(page, reverse("backoffice:test_extra_attempt", args=[self.test1.pk, self.emp1.pk]))
        self.assertContains(page, "1 / 3")
        page = self.get(self.trainer, "employee_detail", self.emp1.pk, tab="tutorials")
        row = TutorialProgress.objects.get(user=self.emp1, tutorial=self.tut1)
        self.assertContains(page, reverse("backoffice:progress_unassign", args=[row.pk]))

    # ── Feedback ───────────────────────────────────────────────────────────
    def test_remove_feedback_recipient(self):
        self.publish_test()
        Feedback.objects.filter(pk=self.fb1.pk).update(test=self.test1)
        self.fb1.refresh_from_db()
        publish_feedback(self.fb1)
        recipient = FeedbackRecipient.objects.get(feedback=self.fb1, user=self.emp1)
        self.assertTrue(TestAssignment.objects.filter(test=self.test1, user=self.emp1).exists())
        detail = self.get(self.trainer, "feedback_detail", self.fb1.pk)
        self.assertContains(detail, reverse("backoffice:feedback_recipient_remove", args=[recipient.pk]))
        self.post(self.trainer, "feedback_recipient_remove", recipient.pk)
        self.assertFalse(FeedbackRecipient.objects.filter(pk=recipient.pk).exists())
        self.assertFalse(TestAssignment.objects.filter(test=self.test1, user=self.emp1).exists())
        self.assertTrue(audited("feedback.recipient_remove", entity_id=str(self.fb1.pk)))
        self.client.force_login(self.emp1)
        self.assertEqual(self.client.get(reverse("portal:feedback_detail", args=[self.fb1.number])).status_code, 404)


class TestBuilderDeleteButtonTests(AdminTestCase):
    def test_delete_button_follows_the_view_rule(self):
        page = self.get(self.trainer, "test_builder", self.test1.pk)
        self.assertTrue(page.context["can_delete"])
        # an attempt that was never submitted (or by someone outside the scope) still blocks deletion
        TestAttempt.objects.create(test=self.test1, user=self.other, attempt_number=1)
        page = self.get(self.trainer, "test_builder", self.test1.pk)
        self.assertFalse(page.context["can_delete"])
        self.assertNotContains(page, 'value="delete"')
        self.post(self.trainer, "test_status", self.test1.pk, data={"action": "delete"})
        self.assertTrue(Test.objects.filter(pk=self.test1.pk).exists())
