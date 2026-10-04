"""
Admin panel: managing everything from the browser — organisations & client accounts, deleting users,
assignment adjustments (unassign, due dates, test attempts), project deletion, website enquiries and
company-wide onboarding.

    DB_TEST_NAME=test_skyleon_manage python manage.py test apps.backoffice.test_manage
"""

from django.urls import reverse
from django.utils import timezone

from apps.assessments.models import Test, TestAssignment, TestAttempt
from apps.assessments.services import start_attempt, submit_attempt, test_state
from apps.comms.models import Notification
from apps.core.choices import ContentStatus, ProgressStatus
from apps.core.models import AuditLog
from apps.feedback.models import Feedback, FeedbackRecipient
from apps.feedback.services import publish_feedback
from apps.training.models import TutorialProgress

from .tests import AdminTestCase


def audited(action, **filters):
    return AuditLog.objects.filter(action=action, **filters).exists()


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
