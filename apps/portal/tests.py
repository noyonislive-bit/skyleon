"""
Employee portal tests.

    DB_TEST_NAME=test_skyleon_portal python manage.py test apps.portal
"""

from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User, UserStatus
from apps.assessments.models import (
    Question,
    QuestionOption,
    QuestionType,
    Test,
    TestAssignment,
    TestAttempt,
)
from apps.comms.models import (
    Announcement,
    AnnouncementRead,
    Meeting,
    MeetingInvite,
    Notification,
)
from apps.core.choices import ContentStatus, ProgressStatus
from apps.feedback.models import Feedback, FeedbackRecipient
from apps.projects.models import Guideline, GuidelineAck, Project, ProjectMember, Team
from apps.storage.models import MediaAsset, MediaKind, MediaProvider, MediaStatus
from apps.training.models import (
    OnboardingCompletion,
    OnboardingStep,
    OnboardingStepType,
    Tutorial,
    TutorialProgress,
)

PASSWORD = "Portal@12345"
PUB = ContentStatus.PUBLISHED


def make_user(email, role=Role.EMPLOYEE, status=UserStatus.ACTIVE, **extra):
    return User.objects.create_user(email=email, password=PASSWORD, name=email.split("@")[0].title(), role=role,
                                    status=status, **extra)


def video(duration=100.0, status=MediaStatus.READY):
    return MediaAsset.objects.create(
        kind=MediaKind.VIDEO, provider=MediaProvider.EXTERNAL, external_url="https://cdn.example.com/v.webm",
        mime_type="video/webm", duration_sec=duration, status=status, purpose="tutorial",
    )


def make_test(title, project=None, *, passing=50, attempts=2, kind="training"):
    t = Test.objects.create(title=title, project=project, kind=kind, passing_score=passing, attempt_limit=attempts,
                            status=PUB, published_at=timezone.now())
    q1 = Question.objects.create(test=t, order=1, qtype=QuestionType.SINGLE_CHOICE, prompt="Pick A", explanation="A is right")
    QuestionOption.objects.create(question=q1, order=1, text="Alpha", is_correct=True)
    QuestionOption.objects.create(question=q1, order=2, text="Bravo", is_correct=False)
    q2 = Question.objects.create(test=t, order=2, qtype=QuestionType.MULTI_SELECT, prompt="Pick both")
    QuestionOption.objects.create(question=q2, order=1, text="One", is_correct=True)
    QuestionOption.objects.create(question=q2, order=2, text="Two", is_correct=True)
    QuestionOption.objects.create(question=q2, order=3, text="Three", is_correct=False)
    return t


def correct_answers(test):
    return {
        f"q_{q.pk}": [str(o.pk) for o in q.options.all() if o.is_correct] for q in test.questions.all()
    }


class PortalTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.proj_a = Project.objects.create(name="Alpha project", slug="alpha", code="ALP-01")
        cls.proj_b = Project.objects.create(name="Beta project", slug="beta", code="BET-01")
        cls.team_a = Team.objects.create(project=cls.proj_a, name="Team A")

        cls.emp = make_user("emp@example.com")
        cls.other = make_user("other@example.com")
        cls.pending = make_user("pending@example.com", status=UserStatus.PENDING)
        cls.client_user = make_user("client@example.com", role=Role.CLIENT)
        cls.pm = make_user("pm@example.com", role=Role.PROJECT_MANAGER)
        ProjectMember.objects.create(project=cls.proj_a, user=cls.emp, team=cls.team_a)
        ProjectMember.objects.create(project=cls.proj_b, user=cls.other)
        ProjectMember.objects.create(project=cls.proj_a, user=cls.pm, role="manager")

        cls.tut_a = Tutorial.objects.create(title="Alpha tutorial", project=cls.proj_a, video=video(), status=PUB, published_at=now)
        cls.tut_b = Tutorial.objects.create(title="Beta tutorial", project=cls.proj_b, video=video(), status=PUB, published_at=now)
        cls.tut_global = Tutorial.objects.create(title="Company tutorial", video=video(), status=PUB, published_at=now)
        cls.tut_draft = Tutorial.objects.create(title="Draft tutorial", project=cls.proj_a, video=video(), status=ContentStatus.DRAFT)
        cls.tut_processing = Tutorial.objects.create(title="Processing", project=cls.proj_a, status=PUB, published_at=now,
                                                     video=video(status=MediaStatus.UPLOADING))
        TutorialProgress.objects.create(tutorial=cls.tut_a, user=cls.emp, assigned=True)

        cls.test_a = make_test("Alpha test", cls.proj_a)
        cls.test_b = make_test("Beta test", cls.proj_b)
        cls.fb_test = make_test("Feedback check", cls.proj_a, kind="feedback", passing=100)
        cls.fb_a = Feedback.objects.create(topic="Hand visibility", explanation="Close the segment.", project=cls.proj_a,
                                           video=video(30), test=cls.fb_test, status=PUB, published_at=now)
        cls.fb_text = Feedback.objects.create(topic="Naming", explanation="Use specific names.", project=cls.proj_a,
                                              status=PUB, published_at=now)
        cls.fb_b = Feedback.objects.create(topic="Boxes", explanation="Tight boxes.", project=cls.proj_b, status=PUB, published_at=now)
        cls.rec_a = FeedbackRecipient.objects.create(feedback=cls.fb_a, user=cls.emp)
        cls.rec_text = FeedbackRecipient.objects.create(feedback=cls.fb_text, user=cls.emp)
        FeedbackRecipient.objects.create(feedback=cls.fb_b, user=cls.other)
        TestAssignment.objects.create(test=cls.fb_test, user=cls.emp)

        cls.guideline = Guideline.objects.create(project=cls.proj_a, title="Rules", content="# Rules", version="2.0")
        cls.step1 = OnboardingStep.objects.create(project=cls.proj_a, order=1, step_type=OnboardingStepType.WELCOME, title="Welcome")
        cls.step2 = OnboardingStep.objects.create(project=cls.proj_a, order=2, step_type=OnboardingStepType.TUTORIAL,
                                                  title="Watch", tutorial=cls.tut_a)
        cls.step3 = OnboardingStep.objects.create(project=cls.proj_a, order=3, step_type=OnboardingStepType.COMMON_MISTAKES,
                                                  title="Mistakes", guideline=cls.guideline)
        cls.ann = Announcement.objects.create(title="Hello", body="**Hi**", project=cls.proj_a)
        Announcement.objects.create(title="Beta only", body="x", project=cls.proj_b)
        meeting = Meeting.objects.create(title="Calibration", starts_at=now + timedelta(days=1), project=cls.proj_a,
                                         meeting_url="https://meet.example.com/x")
        MeetingInvite.objects.create(meeting=meeting, user=cls.emp)

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.emp)

    def hb(self, url, payload, client=None):
        import json

        return (client or self.c).post(url, data=json.dumps(payload), content_type="application/json")


class AccessControlTests(PortalTestBase):
    def test_anonymous_redirected_to_login(self):
        resp = Client().get(reverse("portal:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])

    def test_pending_user_redirected_to_pending_page(self):
        c = Client()
        c.force_login(self.pending)
        resp = c.get(reverse("portal:training"))
        self.assertRedirects(resp, reverse("accounts:pending"), fetch_redirect_response=False)

    def test_client_forbidden(self):
        c = Client()
        c.force_login(self.client_user)
        self.assertEqual(c.get(reverse("portal:dashboard")).status_code, 403)
        self.assertEqual(c.get(reverse("portal:tutorial_detail", args=[self.tut_global.pk])).status_code, 403)

    def test_api_returns_json_403_for_anonymous(self):
        resp = self.hb(reverse("portal:tutorial_heartbeat", args=[self.tut_a.pk]), {"duration": 100, "ranges": [[0, 5]]}, Client())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"], "forbidden")

    def test_other_project_content_hidden(self):
        self.assertEqual(self.c.get(reverse("portal:tutorial_detail", args=[self.tut_b.pk])).status_code, 404)
        self.assertEqual(self.c.get(reverse("portal:project_detail", args=["beta"])).status_code, 404)
        self.assertEqual(self.c.get(reverse("portal:test_detail", args=[self.test_b.pk])).status_code, 404)
        self.assertEqual(self.c.get(reverse("portal:feedback_detail", args=[self.fb_b.number])).status_code, 404)
        resp = self.hb(reverse("portal:tutorial_heartbeat", args=[self.tut_b.pk]), {"duration": 100, "ranges": [[0, 5]]})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(TutorialProgress.objects.filter(tutorial=self.tut_b, user=self.emp).exists())

    def test_draft_content_hidden(self):
        self.assertEqual(self.c.get(reverse("portal:tutorial_detail", args=[self.tut_draft.pk])).status_code, 404)
        resp = self.c.get(reverse("portal:training"))
        self.assertNotContains(resp, "Draft tutorial")
        self.assertNotContains(resp, "Beta tutorial")
        self.assertContains(resp, "Alpha tutorial")
        self.assertContains(resp, "Company tutorial")

    def test_feedback_only_for_recipients(self):
        # Same project, but not a recipient → 404.
        c = Client()
        c.force_login(self.pm)
        self.assertEqual(c.get(reverse("portal:feedback_detail", args=[self.fb_a.number])).status_code, 404)

    def test_removed_member_loses_access(self):
        ProjectMember.objects.filter(user=self.emp, project=self.proj_a).delete()
        self.assertEqual(self.c.get(reverse("portal:tutorial_detail", args=[self.tut_a.pk])).status_code, 404)
        self.assertEqual(self.c.get(reverse("portal:feedback_detail", args=[self.fb_a.number])).status_code, 404)
        self.assertEqual(self.c.get(reverse("portal:tutorial_detail", args=[self.tut_global.pk])).status_code, 200)

    def test_announcements_scoped(self):
        resp = self.c.get(reverse("portal:announcements"))
        self.assertContains(resp, "Hello")
        self.assertNotContains(resp, "Beta only")

    def test_all_pages_render_for_employee_and_staff(self):
        attempt = TestAttempt.objects.create(test=self.test_a, user=self.emp, attempt_number=1,
                                             data={"order": list(self.test_a.questions.values_list("pk", flat=True))})
        urls = [
            reverse("portal:dashboard"), reverse("portal:onboarding"), reverse("portal:projects"),
            reverse("portal:project_detail", args=["alpha"]),
            reverse("portal:guideline_detail", args=["alpha", self.guideline.pk]),
            reverse("portal:training"), reverse("portal:training") + "?status=completed&cadence=daily&q=x&project=company",
            reverse("portal:tutorial_detail", args=[self.tut_a.pk]),
            reverse("portal:tutorial_detail", args=[self.tut_processing.pk]),
            reverse("portal:feedback"), reverse("portal:feedback") + "?tab=pending",
            reverse("portal:feedback_detail", args=[self.fb_a.number]),
            reverse("portal:tests"), reverse("portal:tests") + "?tab=completed",
            reverse("portal:test_detail", args=[self.test_a.pk]),
            reverse("portal:test_take", args=[attempt.pk]),
            reverse("portal:results"), reverse("portal:announcements"), reverse("portal:announcement_detail", args=[self.ann.pk]),
            reverse("portal:meetings"), reverse("portal:notifications"), reverse("portal:notifications_menu"),
            reverse("portal:profile"), reverse("portal:history"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 200)
        pm = Client()
        pm.force_login(self.pm)
        for url in [reverse("portal:dashboard"), reverse("portal:project_detail", args=["alpha"]),
                    reverse("portal:tutorial_detail", args=[self.tut_a.pk]), reverse("portal:tests")]:
            with self.subTest(staff=url):
                self.assertEqual(pm.get(url).status_code, 200)

    def test_processing_video_message(self):
        self.assertContains(self.c.get(reverse("portal:tutorial_detail", args=[self.tut_processing.pk])), "still processing")

    def test_dashboard_query_count_is_bounded(self):
        self.c.get(reverse("portal:dashboard"))  # warm up (session, content types)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.c.get(reverse("portal:dashboard")).status_code, 200)
        self.assertLess(len(ctx.captured_queries), 45)


class HeartbeatTests(PortalTestBase):
    def url(self):
        return reverse("portal:tutorial_heartbeat", args=[self.tut_a.pk])

    def rewind(self, seconds):
        """Pretend the last heartbeat / first view happened `seconds` ago."""
        past = timezone.now() - timedelta(seconds=seconds)
        TutorialProgress.objects.filter(tutorial=self.tut_a, user=self.emp).update(last_heartbeat_at=past, first_viewed_at=past)

    def test_heartbeat_records_progress(self):
        resp = self.hb(self.url(), {"duration": 100, "position": 10, "ranges": [[0, 10]]})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], ProgressStatus.IN_PROGRESS)
        self.assertAlmostEqual(data["percent"], 10, delta=0.5)
        p = TutorialProgress.objects.get(tutorial=self.tut_a, user=self.emp)
        self.assertEqual(p.last_position_sec, 10)
        self.assertEqual(p.watched_ranges, [[0.0, 10.0]])

    def test_forged_full_completion_in_one_call_rejected(self):
        resp = self.hb(self.url(), {"duration": 100, "position": 100, "ranges": [[0, 100]]})
        data = resp.json()
        self.assertFalse(data["completed"])
        self.assertLessEqual(data["watched_seconds"], 30)
        self.assertNotEqual(TutorialProgress.objects.get(tutorial=self.tut_a, user=self.emp).status, ProgressStatus.COMPLETED)

    def test_rapid_fire_heartbeats_are_throttled(self):
        self.hb(self.url(), {"duration": 100, "position": 30, "ranges": [[0, 30]]})
        for _ in range(5):
            data = self.hb(self.url(), {"duration": 100, "position": 100, "ranges": [[0, 100]]}).json()
            self.assertTrue(data["throttled"])
        self.assertLessEqual(TutorialProgress.objects.get(tutorial=self.tut_a, user=self.emp).watched_seconds, 30)

    def test_coverage_cannot_outrun_wall_clock(self):
        """Forging with a heartbeat every few seconds can't run ahead of ~2× real time."""
        rows = TutorialProgress.objects.filter(tutorial=self.tut_a, user=self.emp)
        self.hb(self.url(), {"duration": 100, "position": 30, "ranges": [[0, 30]]})
        now = timezone.now()
        rows.update(last_heartbeat_at=now - timedelta(seconds=4), first_viewed_at=now - timedelta(seconds=4))
        data = self.hb(self.url(), {"duration": 100, "position": 100, "ranges": [[0, 100]]}).json()
        self.assertFalse(data["completed"])
        watched = data["watched_seconds"]
        self.assertLessEqual(watched, (4 + 15) * 2 + 0.5)  # service ceiling: 2× (time since first view + grace)
        # 8 s after the first view the total still cannot run ahead of 2× wall-clock time.
        now = timezone.now()
        rows.update(last_heartbeat_at=now - timedelta(seconds=4), first_viewed_at=now - timedelta(seconds=8))
        data = self.hb(self.url(), {"duration": 100, "position": 100, "ranges": [[0, 100]]}).json()
        self.assertFalse(data["completed"])
        self.assertLessEqual(data["watched_seconds"], (8 + 15) * 2 + 0.5)

    def test_real_viewing_completes(self):
        self.hb(self.url(), {"duration": 100, "position": 30, "ranges": [[0, 30]]})
        self.rewind(60)
        data = self.hb(self.url(), {"duration": 100, "position": 95, "ranges": [[0, 95]]}).json()
        self.assertTrue(data["completed"])
        self.assertEqual(data["status"], ProgressStatus.COMPLETED)
        self.assertTrue(data["completed_at"])
        resp = self.c.get(reverse("portal:tutorial_detail", args=[self.tut_a.pk]))
        self.assertContains(resp, "recorded on")

    def test_stored_duration_wins_over_client(self):
        data = self.hb(self.url(), {"duration": 10, "position": 10, "ranges": [[0, 10]]}).json()
        self.assertAlmostEqual(data["percent"], 10, delta=0.5)  # 10 s of the stored 100 s, not 100 %

    def test_unknown_duration_is_bounded(self):
        self.tut_a.video.duration_sec = None
        self.tut_a.video.save()
        self.assertEqual(self.hb(self.url(), {"duration": "abc", "ranges": [[0, 5]]}).status_code, 400)
        self.assertEqual(self.hb(self.url(), {"duration": 10 ** 9, "position": 5, "ranges": [[0, 5]]}).status_code, 200)

    def test_csrf_required(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.emp)
        self.assertEqual(self.hb(self.url(), {"duration": 100, "ranges": [[0, 5]]}, c).status_code, 403)

    def test_no_manual_complete_endpoint_for_videos(self):
        content = self.c.get(reverse("portal:tutorial_detail", args=[self.tut_a.pk])).content.decode()
        self.assertNotIn("Mark as complete", content)

    def test_feedback_heartbeat_marks_watched_and_unlocks_test(self):
        url = reverse("portal:feedback_heartbeat", args=[self.fb_a.number])
        self.c.get(reverse("portal:feedback_detail", args=[self.fb_a.number]))
        self.hb(url, {"duration": 30, "position": 15, "ranges": [[0, 15]]})
        past = timezone.now() - timedelta(seconds=30)
        FeedbackRecipient.objects.filter(pk=self.rec_a.pk).update(last_heartbeat_at=past, first_viewed_at=past)
        data = self.hb(url, {"duration": 30, "position": 30, "ranges": [[0, 30]]}).json()
        self.assertTrue(data["completed"])
        self.rec_a.refresh_from_db()
        self.assertIsNotNone(self.rec_a.watched_at)
        resp = self.c.post(reverse("portal:test_start", args=[self.fb_test.pk]))
        self.assertTrue(TestAttempt.objects.filter(test=self.fb_test, user=self.emp).exists())
        self.assertIn("/portal/tests/attempt/", resp["Location"])


class FeedbackTests(PortalTestBase):
    def test_opening_tracks_first_view(self):
        self.assertIsNone(self.rec_a.first_viewed_at)
        resp = self.c.get(reverse("portal:feedback_detail", args=[self.fb_a.number]))
        self.assertContains(resp, self.fb_a.display_number)
        self.rec_a.refresh_from_db()
        self.assertIsNotNone(self.rec_a.first_viewed_at)
        self.assertIsNone(self.rec_a.watched_at)  # has a video: opening is not watching

    def test_feedback_without_video_counts_as_watched_on_open(self):
        self.c.get(reverse("portal:feedback_detail", args=[self.fb_text.number]))
        self.rec_text.refresh_from_db()
        self.assertIsNotNone(self.rec_text.watched_at)

    def test_acknowledge(self):
        self.c.post(reverse("portal:feedback_ack", args=[self.fb_a.number]))
        self.rec_a.refresh_from_db()
        self.assertIsNotNone(self.rec_a.acknowledged_at)

    def test_tabs_and_counts(self):
        resp = self.c.get(reverse("portal:feedback"))
        self.assertEqual(resp.context["tab"], "new")
        self.assertEqual(resp.context["counts"]["new"], 2)
        self.c.get(reverse("portal:feedback_detail", args=[self.fb_text.number]))
        self.c.get(reverse("portal:feedback_detail", args=[self.fb_a.number]))
        counts = self.c.get(reverse("portal:feedback") + "?tab=all").context["counts"]
        self.assertEqual((counts["new"], counts["pending"], counts["completed"]), (0, 1, 1))

    def test_feedback_test_requires_watched_video(self):
        resp = self.c.post(reverse("portal:test_start", args=[self.fb_test.pk]))
        self.assertRedirects(resp, reverse("portal:test_detail", args=[self.fb_test.pk]), fetch_redirect_response=False)
        self.assertFalse(TestAttempt.objects.filter(test=self.fb_test, user=self.emp).exists())


class TestFlowTests(PortalTestBase):
    def start(self, test):
        resp = self.c.post(reverse("portal:test_start", args=[test.pk]))
        attempt = TestAttempt.objects.filter(test=test, user=self.emp).order_by("-attempt_number").first()
        return resp, attempt

    def test_start_take_submit_result(self):
        resp, attempt = self.start(self.test_a)
        self.assertRedirects(resp, reverse("portal:test_take", args=[attempt.pk]), fetch_redirect_response=False)
        page = self.c.get(reverse("portal:test_take", args=[attempt.pk]))
        self.assertContains(page, "Pick A")
        for q in page.context["questions"]:
            for o in q["options"]:
                self.assertNotIn("is_correct", o)  # answers never reach the client
        resp = self.c.post(reverse("portal:test_take", args=[attempt.pk]), data=correct_answers(self.test_a))
        self.assertRedirects(resp, reverse("portal:result_detail", args=[attempt.pk]), fetch_redirect_response=False)
        attempt.refresh_from_db()
        self.assertTrue(attempt.passed)
        self.assertEqual(attempt.score, 100)
        result = self.c.get(reverse("portal:result_detail", args=[attempt.pk]))
        self.assertContains(result, "Passed")
        self.assertContains(result, "A is right")  # explanation revealed
        # Submitted attempts can't be re-taken; the take URL goes to the result.
        self.assertRedirects(self.c.get(reverse("portal:test_take", args=[attempt.pk])),
                             reverse("portal:result_detail", args=[attempt.pk]), fetch_redirect_response=False)

    def test_failed_attempt_offers_retake_until_limit(self):
        _, a1 = self.start(self.test_a)
        self.c.post(reverse("portal:test_take", args=[a1.pk]), data={})
        a1.refresh_from_db()
        self.assertFalse(a1.passed)
        self.assertTrue(self.c.get(reverse("portal:result_detail", args=[a1.pk])).context["can_retake"])
        _, a2 = self.start(self.test_a)
        self.assertEqual(a2.attempt_number, 2)
        self.c.post(reverse("portal:test_take", args=[a2.pk]), data={})
        self.assertFalse(self.c.get(reverse("portal:result_detail", args=[a2.pk])).context["can_retake"])
        resp = self.c.post(reverse("portal:test_start", args=[self.test_a.pk]), follow=True)
        self.assertContains(resp, "used all attempts")
        self.assertEqual(TestAttempt.objects.filter(test=self.test_a, user=self.emp).count(), 2)

    def test_hidden_answers_when_reveal_disabled(self):
        Test.objects.filter(pk=self.test_a.pk).update(reveal_answers=False)
        _, attempt = self.start(self.test_a)
        self.c.post(reverse("portal:test_take", args=[attempt.pk]), data=correct_answers(self.test_a))
        resp = self.c.get(reverse("portal:result_detail", args=[attempt.pk]))
        self.assertNotContains(resp, "A is right")
        self.assertNotContains(resp, ">Correct answer<")
        self.assertNotContains(resp, "is-correct")

    def test_other_users_cannot_open_attempt(self):
        _, attempt = self.start(self.test_a)
        c = Client()
        c.force_login(self.other)
        self.assertEqual(c.get(reverse("portal:test_take", args=[attempt.pk])).status_code, 404)
        self.assertEqual(c.post(reverse("portal:test_take", args=[attempt.pk]), data={}).status_code, 404)
        self.assertEqual(c.get(reverse("portal:result_detail", args=[attempt.pk])).status_code, 404)

    def test_expired_timed_attempt_is_submitted(self):
        Test.objects.filter(pk=self.test_a.pk).update(time_limit_min=1)
        _, attempt = self.start(self.test_a)
        TestAttempt.objects.filter(pk=attempt.pk).update(started_at=timezone.now() - timedelta(minutes=10))
        resp = self.c.get(reverse("portal:test_take", args=[attempt.pk]))
        self.assertRedirects(resp, reverse("portal:result_detail", args=[attempt.pk]), fetch_redirect_response=False)
        attempt.refresh_from_db()
        self.assertIsNotNone(attempt.submitted_at)

    def test_timed_attempt_shows_countdown(self):
        Test.objects.filter(pk=self.test_a.pk).update(time_limit_min=15)
        _, attempt = self.start(self.test_a)
        resp = self.c.get(reverse("portal:test_take", args=[attempt.pk]))
        self.assertGreater(resp.context["remaining"], 14 * 60)
        self.assertContains(resp, "data-remaining")

    def test_results_history(self):
        _, attempt = self.start(self.test_a)
        self.c.post(reverse("portal:test_take", args=[attempt.pk]), data=correct_answers(self.test_a))
        resp = self.c.get(reverse("portal:results"))
        self.assertContains(resp, "Alpha test")
        self.assertEqual(resp.context["summary"]["passed"], 1)


class OnboardingTests(PortalTestBase):
    def test_complete_unlocked_manual_step(self):
        resp = self.c.post(reverse("portal:onboarding_complete_step", args=[self.step1.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(OnboardingCompletion.objects.filter(step=self.step1, user=self.emp).exists())

    def test_locked_manual_step_cannot_be_completed(self):
        # step3 is locked: step2 needs the tutorial to be watched first.
        self.c.post(reverse("portal:onboarding_complete_step", args=[self.step1.pk]))
        self.c.post(reverse("portal:onboarding_complete_step", args=[self.step3.pk]))
        self.assertFalse(OnboardingCompletion.objects.filter(step=self.step3, user=self.emp).exists())

    def test_tutorial_step_is_not_manual(self):
        self.c.post(reverse("portal:onboarding_complete_step", args=[self.step1.pk]))
        self.c.post(reverse("portal:onboarding_complete_step", args=[self.step2.pk]))
        self.assertFalse(OnboardingCompletion.objects.filter(step=self.step2, user=self.emp).exists())

    def test_other_project_step_rejected(self):
        step_b = OnboardingStep.objects.create(project=self.proj_b, order=1, title="Beta welcome")
        self.c.post(reverse("portal:onboarding_complete_step", args=[step_b.pk]))
        self.assertFalse(OnboardingCompletion.objects.filter(step=step_b, user=self.emp).exists())

    def test_page_shows_progress_and_manual_button(self):
        resp = self.c.get(reverse("portal:onboarding"))
        self.assertContains(resp, "Mark as complete")
        self.assertEqual(resp.context["overall_total"], 3)

    def test_completed_track_shows_celebration(self):
        OnboardingCompletion.objects.create(step=self.step1, user=self.emp)
        OnboardingCompletion.objects.create(step=self.step3, user=self.emp)
        TutorialProgress.objects.filter(tutorial=self.tut_a, user=self.emp).update(
            status=ProgressStatus.COMPLETED, completed_at=timezone.now(), percent=100
        )
        resp = self.c.get(reverse("portal:onboarding"))
        self.assertEqual(resp.context["overall_percent"], 100)
        self.assertContains(resp, "Onboarding complete")
        self.assertNotContains(resp, "Mark as complete")

    def test_guideline_ack_records_version(self):
        self.c.post(reverse("portal:guideline_ack", args=["alpha", self.guideline.pk]))
        self.assertEqual(GuidelineAck.objects.get(guideline=self.guideline, user=self.emp).version, "2.0")


class NotificationTests(PortalTestBase):
    def test_open_marks_read_and_redirects_internal(self):
        n = Notification.objects.create(user=self.emp, ntype="training", title="New", link="/portal/training/")
        resp = self.c.get(reverse("portal:notification_open", args=[n.pk]))
        self.assertRedirects(resp, "/portal/training/", fetch_redirect_response=False)
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)

    def test_external_links_are_not_followed(self):
        for link in ("https://evil.example.com/", "//evil.example.com/", "javascript:alert(1)", "/\\evil.example.com"):
            n = Notification.objects.create(user=self.emp, ntype="system", title="x", link=link)
            resp = self.c.get(reverse("portal:notification_open", args=[n.pk]))
            self.assertRedirects(resp, reverse("portal:notifications"), fetch_redirect_response=False)

    def test_cannot_open_someone_elses_notification(self):
        n = Notification.objects.create(user=self.other, ntype="system", title="x", link="/portal/")
        self.assertEqual(self.c.get(reverse("portal:notification_open", args=[n.pk])).status_code, 404)
        n.refresh_from_db()
        self.assertIsNone(n.read_at)

    def test_mark_all_read(self):
        Notification.objects.create(user=self.emp, ntype="system", title="a")
        Notification.objects.create(user=self.emp, ntype="system", title="b")
        mine = Notification.objects.create(user=self.other, ntype="system", title="c")
        self.c.post(reverse("portal:notifications_read_all"))
        self.assertFalse(Notification.objects.filter(user=self.emp, read_at__isnull=True).exists())
        mine.refresh_from_db()
        self.assertIsNone(mine.read_at)

    def test_announcement_read_api_and_detail(self):
        resp = self.c.post(reverse("portal:announcement_read", args=[self.ann.pk]))
        self.assertEqual(resp.json()["unread"], 0)
        self.assertTrue(AnnouncementRead.objects.filter(announcement=self.ann, user=self.emp).exists())
        beta = Announcement.objects.get(title="Beta only")
        self.assertEqual(self.c.post(reverse("portal:announcement_read", args=[beta.pk])).status_code, 404)

    def test_sidebar_counts(self):
        Notification.objects.create(user=self.emp, ntype="system", title="a")
        resp = self.c.get(reverse("portal:dashboard"))
        counts = resp.wsgi_request.portal.counts
        self.assertEqual(counts["notifications"], 1)
        self.assertEqual(counts["feedback"], 2)
        self.assertEqual(counts["announcements"], 1)
        self.assertEqual(counts["tests"], 2)  # Alpha test + feedback test


class ProfileTests(PortalTestBase):
    def test_update_profile(self):
        resp = self.c.post(reverse("portal:profile"), {
            "action": "profile", "profile-name": "New Name", "profile-phone": "123", "profile-location": "Dhaka",
            "profile-title": "Annotator", "profile-bio": "", "profile-skills_text": "CVAT, polygon",
        })
        self.assertEqual(resp.status_code, 302)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.name, "New Name")
        self.assertEqual(self.emp.skills, ["CVAT", "polygon"])

    def test_change_password_keeps_session(self):
        resp = self.c.post(reverse("portal:profile"), {
            "action": "password", "pw-old_password": PASSWORD,
            "pw-new_password1": "Brand-New#Pass42", "pw-new_password2": "Brand-New#Pass42",
        })
        self.assertEqual(resp.status_code, 302)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password("Brand-New#Pass42"))
        self.assertEqual(self.c.get(reverse("portal:dashboard")).status_code, 200)

    def test_wrong_old_password(self):
        resp = self.c.post(reverse("portal:profile"), {
            "action": "password", "pw-old_password": "nope", "pw-new_password1": "Brand-New#Pass42",
            "pw-new_password2": "Brand-New#Pass42",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["password_form"].errors)
