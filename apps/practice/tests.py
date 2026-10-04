from django.test import SimpleTestCase

from .scoring import clean_clips, score_attempt, uncovered


class ScoringTests(SimpleTestCase):
    def test_perfect_match(self):
        ref = [(10, 12), (12.5, 15), (16, 20)]
        r = score_attempt(ref, ref, 10, 20, 0.5)
        self.assertEqual(r["boundary_f1"], 100.0)
        self.assertEqual(r["mean_iou"], 100.0)
        self.assertGreater(r["score"], 95)

    def test_small_offsets_within_tolerance(self):
        ref = [(10, 12), (12.5, 15)]
        usr = [(10.2, 11.8), (12.6, 15.3)]
        r = score_attempt(usr, ref, 10, 15, 0.5)
        self.assertEqual(r["boundary_f1"], 100.0)
        self.assertFalse([i for i in r["issues"] if i["kind"] in ("missed", "boundary")])

    def test_missed_and_late_clips_reported(self):
        ref = [(10, 12), (13, 16)]
        usr = [(11.0, 12.0)]
        r = score_attempt(usr, ref, 10, 16, 0.5)
        kinds = {i["kind"] for i in r["issues"]}
        self.assertIn("missed", kinds)
        self.assertIn("boundary", kinds)
        self.assertLess(r["score"], 60)

    def test_no_reference_scores_coverage(self):
        r = score_attempt([(0, 5)], [], 0, 10, 0.5)
        self.assertEqual(r["score"], 50.0)
        self.assertIsNone(r["boundary_f1"])

    def test_uncovered_and_clean(self):
        self.assertEqual(uncovered([(2, 4), (3, 5)], 0, 10), [(0, 2), (5, 10)])
        self.assertEqual(clean_clips([[5, 3], ["x", 1], [0, 0.01], [9, 99]], 0, 10), [(3.0, 5.0), (9.0, 10.0)])


import json  # noqa: E402

from django.test import TestCase  # noqa: E402
from django.urls import reverse  # noqa: E402

from apps.accounts.models import Role, User, UserStatus  # noqa: E402
from apps.accounts.services import approve_user  # noqa: E402
from apps.projects.models import Project  # noqa: E402
from apps.projects.services import add_member  # noqa: E402
from apps.storage.models import MediaAsset  # noqa: E402

from .models import AttemptStatus, PracticeAttempt, PracticeTask  # noqa: E402


class PracticeViewTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="P", slug="p", code="P-1")
        self.other = Project.objects.create(name="O", slug="o", code="O-1")
        video = MediaAsset.objects.create(kind="video", provider="external", external_url="https://example.com/v.mp4", status="ready", duration_sec=60)
        self.task = PracticeTask.objects.create(title="T", project=self.project, video=video, range_start=0, range_end=20,
                                                reference_clips=[[1, 5], [6, 10]], status="published", passing_score=70)
        self.hidden = PracticeTask.objects.create(title="H", project=self.other, video=video, status="published")
        self.emp = User.objects.create_user("e@example.com", "pw-Strong-1", name="E")
        approve_user(self.emp, send_email=False)
        add_member(self.project, self.emp, notify_user=False)
        self.trainer = User.objects.create_user("t@example.com", "pw-Strong-1", name="T", role=Role.TRAINER, status=UserStatus.ACTIVE)
        add_member(self.project, self.trainer, notify_user=False)

    def post(self, name, task, data):
        return self.client.post(reverse(name, args=[task.pk]), json.dumps(data), content_type="application/json")

    def test_employee_sees_only_own_project_tasks(self):
        self.client.force_login(self.emp)
        self.assertContains(self.client.get(reverse("practice:list")), "T")
        self.assertEqual(self.client.get(reverse("practice:workspace", args=[self.task.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("practice:workspace", args=[self.hidden.pk])).status_code, 404)

    def test_save_submit_and_result(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.post("practice:save", self.task, {"clips": [[1, 5]]}).status_code, 200)
        r = self.post("practice:submit", self.task, {"clips": [[1.1, 5], [6, 9.8], [10.5, 20]], "timeSpent": 30})
        body = r.json()
        self.assertTrue(body["passed"], body)
        attempt = PracticeAttempt.objects.get(user=self.emp, status=AttemptStatus.SUBMITTED)
        self.assertEqual(self.client.get(body["resultUrl"]).status_code, 200)
        other = User.objects.create_user("x@example.com", "pw-Strong-1", name="X")
        approve_user(other, send_email=False)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("practice:result", args=[attempt.pk])).status_code, 404)

    def test_management_permissions(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.client.get(reverse("practice:manage")).status_code, 403)
        self.client.force_login(self.trainer)
        self.assertEqual(self.client.get(reverse("practice:manage")).status_code, 200)
        self.assertEqual(self.client.get(reverse("practice:manage_edit", args=[self.hidden.pk])).status_code, 404)
        r = self.post("practice:manage_reference_save", self.task, {"clips": [[2, 4]]})
        self.assertEqual(r.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.reference_clips, [[2.0, 4.0]])
        self.assertEqual(self.client.get(reverse("practice:manage_settings")).status_code, 403)  # super admin only


from django.utils import timezone  # noqa: E402

from apps.training.models import Tutorial  # noqa: E402

from .forms import PracticeTaskForm, parse_time  # noqa: E402
from .services import coerce_seconds  # noqa: E402


class PracticeHardeningTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="P", slug="p", code="P-1")
        self.other = Project.objects.create(name="O", slug="o", code="O-1")
        self.video = MediaAsset.objects.create(kind="video", provider="external", external_url="https://example.com/v.mp4",
                                               status="ready", duration_sec=60)
        self.task = PracticeTask.objects.create(title="T", project=self.project, video=self.video, range_start=0, range_end=20,
                                                reference_clips=[[1, 5]], status="published", passing_score=70)
        self.emp = User.objects.create_user("e@example.com", "pw-Strong-1", name="E")
        approve_user(self.emp, send_email=False)
        add_member(self.project, self.emp, notify_user=False)
        self.trainer = User.objects.create_user("t@example.com", "pw-Strong-1", name="T", role=Role.TRAINER, status=UserStatus.ACTIVE)
        add_member(self.project, self.trainer, notify_user=False)
        self.pm = User.objects.create_user("pm@example.com", "pw-Strong-1", name="PM", role=Role.PROJECT_MANAGER, status=UserStatus.ACTIVE)
        add_member(self.project, self.pm, notify_user=False)

    def post(self, name, task, data, raw=None):
        body = raw if raw is not None else json.dumps(data)
        return self.client.post(reverse(name, args=[task.pk]), body, content_type="application/json")

    def test_parse_time_rejects_non_finite(self):
        for value in ("inf", "nan", "-1", "1e999", "00:inf"):
            with self.assertRaises(ValueError, msg=value):
                parse_time(value)
        self.assertEqual(parse_time("01:15"), 75)
        form = PracticeTaskForm({"title": "X", "range_start": "inf", "tolerance_sec": 0.5, "passing_score": 80, "order": 0},
                                user=self.trainer, projects=Project.objects.all())
        self.assertFalse(form.is_valid())
        self.assertIn("range_start", form.errors)

    def test_passing_score_bounds(self):
        for score in (0, 101):
            form = PracticeTaskForm({"title": "X", "tolerance_sec": 0.5, "passing_score": score, "order": 0},
                                    user=self.trainer, projects=Project.objects.all())
            self.assertIn("passing_score", form.errors, score)

    def test_video_choices_are_scoped(self):
        p1_tutorial_video = MediaAsset.objects.create(kind="video", provider="local", storage_key="a", status="ready")
        Tutorial.objects.create(title="P1", project=self.project, video=p1_tutorial_video)
        p2_tutorial_video = MediaAsset.objects.create(kind="video", provider="local", storage_key="b", status="ready")
        Tutorial.objects.create(title="P2", project=self.other, video=p2_tutorial_video)
        own = MediaAsset.objects.create(kind="video", provider="local", storage_key="c", status="ready", uploaded_by=self.trainer)
        stray = MediaAsset.objects.create(kind="video", provider="local", storage_key="d", status="ready", uploaded_by=self.pm)
        choices = set(PracticeTaskForm(user=self.trainer, projects=Project.objects.all()).fields["video"].queryset)
        self.assertEqual(choices, {p1_tutorial_video, own, self.video})
        self.assertNotIn(stray, choices)  # someone else's unattached upload
        # picking a video outside the scope is rejected
        form = PracticeTaskForm({"title": "X", "project": self.project.pk, "video": str(p2_tutorial_video.pk), "tolerance_sec": 0.5,
                                 "passing_score": 80, "order": 0}, user=self.trainer, projects=Project.objects.all())
        self.assertIn("video", form.errors)

    def test_publish_redirect_is_safe(self):
        self.client.force_login(self.trainer)
        r = self.client.post(reverse("practice:manage_publish", args=[self.task.pk]), {"action": "unpublish", "next": "https://evil.example/x"})
        self.assertEqual(r["Location"], reverse("practice:manage"))
        r = self.client.post(reverse("practice:manage_publish", args=[self.task.pk]), {"next": "/admin/practice/"})
        self.assertEqual(r["Location"], "/admin/practice/")

    def test_reference_save_rejects_malformed_payload(self):
        self.client.force_login(self.trainer)
        for raw in ("not json", json.dumps({"clips": "x"}), json.dumps([1, 2]), json.dumps({})):
            r = self.post("practice:manage_reference_save", self.task, None, raw=raw)
            self.assertEqual(r.status_code, 400, raw)
        self.task.refresh_from_db()
        self.assertEqual(self.task.reference_clips, [[1, 5]])
        self.assertEqual(self.post("practice:manage_reference_save", self.task, {"clips": []}).status_code, 200)

    def test_time_spent_is_coerced(self):
        self.assertEqual([coerce_seconds(v) for v in ("abc", "1e3", float("inf"), -5, 10 ** 9, True, None, "30.7")],
                         [None, 1000, None, 0, 24 * 3600, None, None, 30])
        self.client.force_login(self.emp)
        for value in ("abc", "1e3", "Infinity", [1], {"a": 1}):
            self.assertEqual(self.post("practice:save", self.task, {"clips": [[1, 5]], "timeSpent": value}).status_code, 200, value)
        draft = PracticeAttempt.objects.get(user=self.emp, status=AttemptStatus.DRAFT)
        self.assertEqual(draft.time_spent_sec, 1000)
        # max per page session, not a running sum of the autosaves
        self.post("practice:save", self.task, {"clips": [[1, 5]], "timeSpent": 40})
        draft.refresh_from_db()
        self.assertEqual(draft.time_spent_sec, 1000)
        # a non-list "clips" never wipes the draft
        self.post("practice:save", self.task, {"clips": "oops"})
        draft.refresh_from_db()
        self.assertEqual(draft.clips, [[1.0, 5.0]])
        r = self.post("practice:submit", self.task, {"clips": {"0": [1, 5]}, "timeSpent": "abc"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PracticeAttempt.objects.get(pk=draft.pk).clips, [[1.0, 5.0]])

    def test_pm_list_hides_company_wide_tasks_and_counts_are_scoped(self):
        glob = PracticeTask.objects.create(title="Company task", video=self.video, status="published")
        outsider = User.objects.create_user("o@example.com", "pw-Strong-1", name="Outsider")
        approve_user(outsider, send_email=False)
        add_member(self.other, outsider, notify_user=False)
        now = timezone.now()
        PracticeAttempt.objects.create(task=self.task, user=outsider, status=AttemptStatus.SUBMITTED, score=50, submitted_at=now)
        attempt = PracticeAttempt.objects.create(task=self.task, user=self.emp, status=AttemptStatus.SUBMITTED, score=90, passed=True,
                                                 submitted_at=now)
        self.client.force_login(self.pm)
        r = self.client.get(reverse("practice:manage"))
        tasks = list(r.context["tasks"])
        self.assertNotIn(glob, tasks)  # PMs can't edit company-wide tasks (their links would 404)
        row = next(t for t in tasks if t.pk == self.task.pk)
        self.assertEqual((row.n_attempts, row.n_people, row.n_passed), (1, 1, 1))
        results = self.client.get(reverse("practice:manage_results", args=[self.task.pk]))
        self.assertEqual([p["user"] for p in results.context["people"]], [self.emp])
        outsider_attempt = PracticeAttempt.objects.get(user=outsider)
        self.assertEqual(self.client.get(reverse("practice:manage_attempt", args=[outsider_attempt.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("practice:manage_attempt", args=[attempt.pk])).status_code, 200)
        self.client.force_login(self.trainer)  # trainers manage company-wide content
        self.assertIn(glob, list(self.client.get(reverse("practice:manage")).context["tasks"]))

    def test_delete_is_blocked_once_employees_submitted(self):
        PracticeAttempt.objects.create(task=self.task, user=self.emp, status=AttemptStatus.SUBMITTED, score=90)
        self.client.force_login(self.trainer)
        self.client.post(reverse("practice:manage_delete", args=[self.task.pk]))
        self.assertTrue(PracticeTask.objects.filter(pk=self.task.pk).exists())


from apps.comms.models import Notification  # noqa: E402

from .models import AttemptPhase  # noqa: E402
from .scoring import clip_matches  # noqa: E402


class WeeklyReviewTests(TestCase):
    """Employees clip first; the reviewer's answer is published later; then compare and correct."""

    post = PracticeViewTests.post

    def setUp(self):
        PracticeViewTests.setUp(self)
        self.task.kind = "review"
        self.task.reference_clips = []
        self.task.save()

    def publish_answer(self, clips=([1, 5], [6, 10])):
        self.client.force_login(self.trainer)
        self.assertEqual(self.post("practice:manage_reference_save", self.task, {"clips": list(clips)}).status_code, 200)
        r = self.client.post(reverse("practice:manage_answer", args=[self.task.pk]))
        self.assertEqual(r.status_code, 302)
        self.task.refresh_from_db()
        self.assertIsNotNone(self.task.answer_published_at)
        self.client.force_login(self.emp)

    def test_own_work_is_kept_and_unscored_until_the_answer(self):
        self.client.force_login(self.emp)
        self.assertContains(self.client.get(reverse("practice:list")), "সাপ্তাহিক রিভিউ")
        self.assertContains(self.client.get(reverse("practice:workspace", args=[self.task.pk])), "সাপ্তাহিক রিভিউ")
        body = self.post("practice:submit", self.task, {"clips": [[1.2, 5], [7, 10]]}).json()
        self.assertTrue(body["pending"])
        self.assertIsNone(body["score"])
        # can still edit and re-submit before the answer — always the same single attempt
        self.assertEqual(self.post("practice:save", self.task, {"clips": [[1.1, 5], [6.2, 10]]}).status_code, 200)
        self.post("practice:submit", self.task, {"clips": [[1.1, 5], [6.2, 10]]})
        attempts = PracticeAttempt.objects.filter(task=self.task, user=self.emp)
        self.assertEqual(attempts.count(), 1)
        self.assertEqual(attempts.get().clips, [[1.1, 5.0], [6.2, 10.0]])
        # nothing to compare yet
        self.assertRedirects(self.client.get(reverse("practice:review", args=[self.task.pk])), reverse("practice:workspace", args=[self.task.pk]))
        self.assertEqual(self.post("practice:correct_submit", self.task, {"clips": [[1, 5]]}).status_code, 409)

    def test_answer_scores_everyone_then_compare_and_correct(self):
        self.client.force_login(self.emp)
        self.post("practice:submit", self.task, {"clips": [[1, 5]]})  # missed the second action
        self.publish_answer()
        first = PracticeAttempt.objects.get(task=self.task, user=self.emp, phase=AttemptPhase.FIRST)
        self.assertIsNotNone(first.score)
        self.assertLess(first.score, 70)
        self.assertTrue(Notification.objects.filter(user=self.emp, title__contains="রিভিউয়ারের উত্তর").exists())
        # own work is frozen now; the workspace sends you to the comparison
        self.assertEqual(self.post("practice:submit", self.task, {"clips": [[1, 5], [6, 10]]}).status_code, 409)
        self.assertRedirects(self.client.get(reverse("practice:workspace", args=[self.task.pk])), reverse("practice:review", args=[self.task.pk]))
        page = self.client.get(reverse("practice:review", args=[self.task.pk]))
        self.assertContains(page, "রিভিউয়ারের উত্তর")
        self.assertContains(page, "বাদ পড়েছে")
        # correction mode shows the answer as a guide and starts from the employee's own clips
        page = self.client.get(reverse("practice:correct", args=[self.task.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["payload"]["guide"], [[1.0, 5.0], [6.0, 10.0]])
        self.assertEqual(page.context["payload"]["clips"], [[1.0, 5.0]])
        body = self.post("practice:correct_submit", self.task, {"clips": [[1, 5], [6, 10]]}).json()
        self.assertGreater(body["score"], body["firstScore"])
        self.assertEqual(PracticeAttempt.objects.filter(task=self.task, user=self.emp, phase=AttemptPhase.CORRECTION, status="submitted").count(), 1)
        page = self.client.get(reverse("practice:review", args=[self.task.pk]))
        self.assertContains(page, "সংশোধনের পর")
        self.client.force_login(self.trainer)
        results = self.client.get(reverse("practice:manage_results", args=[self.task.pk]))
        self.assertContains(results, "Weekly review")
        self.assertEqual(results.context["review_stats"]["corrected"], 1)

    def test_late_starter_must_submit_own_work_before_seeing_the_answer(self):
        self.publish_answer()
        self.assertRedirects(self.client.get(reverse("practice:correct", args=[self.task.pk])), reverse("practice:workspace", args=[self.task.pk]))
        self.assertEqual(self.client.get(reverse("practice:workspace", args=[self.task.pk])).context["payload"]["guide"], [])
        body = self.post("practice:submit", self.task, {"clips": [[1, 5], [6, 10]]}).json()
        self.assertFalse(body["pending"])
        self.assertTrue(body["resultUrl"].endswith("/review/"))

    def test_answer_needs_a_recording_and_editing_it_rescores(self):
        self.client.force_login(self.trainer)
        self.client.post(reverse("practice:manage_answer", args=[self.task.pk]))
        self.task.refresh_from_db()
        self.assertIsNone(self.task.answer_published_at)
        self.client.force_login(self.emp)
        self.post("practice:submit", self.task, {"clips": [[1, 5], [6, 10]]})
        self.publish_answer(clips=([1, 5],))
        before = PracticeAttempt.objects.get(task=self.task, user=self.emp).score
        self.client.force_login(self.trainer)
        self.post("practice:manage_reference_save", self.task, {"clips": [[1, 5], [6, 10]]})
        after = PracticeAttempt.objects.get(task=self.task, user=self.emp).score
        self.assertGreater(after, before)

    def test_clip_matches(self):
        rows = clip_matches([(1, 5), (6.8, 10)], [(1, 5), (6, 10), (12, 14)], 0.5)
        self.assertEqual([r["status"] for r in rows], ["ok", "near", "missed"])
