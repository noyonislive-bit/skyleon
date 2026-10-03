import json
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import Role, User, UserStatus
from apps.accounts.services import approve_user
from apps.projects.models import Project
from apps.projects.services import add_member

from .importer import GuideImportError, export_guide, import_guide
from .models import Guide, GuideProgress, GuideStep
from .video import embed_info, parse_start

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_guide.json"


class VideoEmbedTests(SimpleTestCase):
    def test_youtube_variants(self):
        for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ",
                    "https://www.youtube.com/shorts/dQw4w9WgXcQ", "https://www.youtube.com/embed/dQw4w9WgXcQ"):
            info = embed_info(url)
            self.assertEqual(info["kind"], "iframe", url)
            self.assertIn("youtube-nocookie.com/embed/dQw4w9WgXcQ", info["src"])
        self.assertIn("start=90", embed_info("https://youtu.be/dQw4w9WgXcQ", 90)["src"])

    def test_direct_files_and_hls(self):
        self.assertEqual(embed_info("https://cdn.example.com/a.mp4")["kind"], "video")
        self.assertEqual(embed_info("https://cdn.example.com/master.m3u8?token=1")["kind"], "hls")

    def test_drive_and_vimeo(self):
        self.assertIn("/preview", embed_info("https://drive.google.com/file/d/1A2b3C4d5E6f7G8h9I0jKlMn/view?usp=sharing")["src"])
        self.assertIn("player.vimeo.com/video/76979871", embed_info("https://vimeo.com/76979871")["src"])

    def test_rejects_non_http(self):
        self.assertIsNone(embed_info("javascript:alert(1)"))
        self.assertIsNone(embed_info("ftp://example.com/a.mp4"))

    def test_parse_start(self):
        self.assertEqual(parse_start("1:30"), 90)
        self.assertEqual(parse_start("75"), 75)
        self.assertIsNone(parse_start("abc"))


class GuideFlowTests(TestCase):
    def setUp(self):
        self.data = json.loads(SAMPLE.read_text(encoding="utf-8"))
        self.project = Project.objects.create(name="P", slug="p", code="P-1")
        self.emp = User.objects.create_user("e@example.com", "pw-Strong-1", name="E")
        approve_user(self.emp, send_email=False)
        add_member(self.project, self.emp, notify_user=False)
        self.trainer = User.objects.create_user("t@example.com", "pw-Strong-1", name="T", role=Role.TRAINER, status=UserStatus.ACTIVE)

    def test_import_export_round_trip_and_replace_keeps_progress(self):
        result = import_guide(self.data, publish=True)
        guide = result.guide
        self.assertEqual((result.sections, result.steps), (2, 4))
        step = GuideStep.objects.get(guide=guide, anchor="cut-with-n")
        GuideProgress.objects.create(user=self.emp, step=step)
        again = import_guide(export_guide(guide), replace=True)
        self.assertEqual(again.guide.pk, guide.pk)
        self.assertTrue(GuideProgress.objects.filter(user=self.emp, step__anchor="cut-with-n").exists())

    def test_import_validation_errors(self):
        bad = {**self.data, "sections": [{"title": "", "steps": [{"title": "x", "video_url": "javascript:1"}]}]}
        with self.assertRaises(GuideImportError) as ctx:
            import_guide(bad)
        self.assertTrue(ctx.exception.errors)

    def test_reader_access_and_progress(self):
        guide = import_guide(self.data, publish=True).guide
        hidden = import_guide({**self.data, "slug": "other-project", "project_code": None}).guide  # draft
        self.client.force_login(self.emp)
        self.assertContains(self.client.get(reverse("guides:list")), guide.title)
        self.assertEqual(self.client.get(reverse("guides:detail", args=[guide.slug])).status_code, 200)
        self.assertEqual(self.client.get(reverse("guides:detail", args=[hidden.slug])).status_code, 404)  # drafts hidden
        step = GuideStep.objects.filter(guide=guide).first()
        r = self.client.post(reverse("guides:done", args=[step.pk]), json.dumps({"done": True}),
                             content_type="application/json", HTTP_ACCEPT="application/json")
        self.assertEqual(r.json()["doneCount"], 1)
        self.assertEqual(r.json()["percent"], 25)
        r = self.client.get(reverse("guides:step", args=[guide.slug, step.anchor]))
        self.assertEqual(r.status_code, 200)

    def test_project_guides_only_for_members(self):
        outsider = User.objects.create_user("o@example.com", "pw-Strong-1", name="O")
        approve_user(outsider, send_email=False)
        guide = import_guide({**self.data, "slug": "proj-guide", "project_code": "P-1"}, publish=True).guide
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse("guides:detail", args=[guide.slug])).status_code, 404)
        self.client.force_login(self.emp)
        self.assertEqual(self.client.get(reverse("guides:detail", args=[guide.slug])).status_code, 200)

    def test_admin_pages(self):
        guide = import_guide(self.data).guide
        step = GuideStep.objects.filter(guide=guide).first()
        self.client.force_login(self.emp)
        self.assertEqual(self.client.get(reverse("guides:manage")).status_code, 403)
        self.client.force_login(self.trainer)
        for url in (reverse("guides:manage"), reverse("guides:manage_edit", args=[guide.pk]),
                    reverse("guides:manage_progress", args=[guide.pk]), reverse("guides:manage_import"),
                    reverse("guides:manage_step_edit", args=[step.pk]), reverse("guides:manage_new")):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        r = self.client.post(reverse("guides:manage_publish", args=[guide.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Guide.objects.get(pk=guide.pk).is_published)
        r = self.client.get(reverse("guides:manage_export", args=[guide.pk]))
        self.assertEqual(json.loads(r.content)["slug"], guide.slug)
