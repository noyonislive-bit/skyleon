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
