from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.accounts.models import Role, User
from apps.assessments.models import Test
from apps.comms.models import Announcement, EmailMessage, Meeting
from apps.core.management.commands import seed_demo
from apps.feedback.models import Feedback
from apps.guides.models import Guide
from apps.practice.models import PracticeAttempt, PracticeTask
from apps.projects.models import Project
from apps.storage.models import MediaAsset
from apps.training.models import Tutorial
from apps.website.models import JobApplication, QuoteRequest


def run(*args, **opts):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out, **opts)
    return out.getvalue()


def counts():
    return {m.__name__: m.objects.count() for m in (User, Project, Tutorial, Test, Feedback, PracticeTask, PracticeAttempt,
                                                     Announcement, Meeting, Guide, QuoteRequest, JobApplication)}


@override_settings(DEBUG=True)
@mock.patch.object(seed_demo.shutil, "which", return_value=None)  # no ffmpeg: sample videos are links, the test stays fast
class SampleDataTests(TestCase):
    def test_full_set_once_then_never_duplicated(self, _which):
        run()
        first = counts()
        self.assertEqual(first["Project"], 3)
        self.assertEqual(first["Tutorial"], 10)
        self.assertEqual(first["Test"], 6)
        self.assertEqual(first["Feedback"], 4)
        self.assertEqual(first["PracticeTask"], 3)
        self.assertEqual(first["Guide"], 1)
        self.assertGreater(first["PracticeAttempt"], 0)
        self.assertFalse(EmailMessage.objects.exists())  # sample data never emails anyone
        self.assertIn("0 new items", run())
        self.assertEqual(counts(), first)
        self.assertIn("up to date", run(if_outdated=True))

    def test_items_you_edited_are_kept(self, _which):
        run()
        t = Tutorial.objects.get(title="অ্যাকশন সেগমেন্টেশনের মূল কথা")
        t.description = "Our own text"
        t.save()
        run()
        t.refresh_from_db()
        self.assertEqual(t.description, "Our own text")

    def test_first_english_version_is_updated_to_bangla(self, _which):
        run()
        Tutorial.objects.filter(title="অ্যাকশন সেগমেন্টেশনের মূল কথা").update(title="Action segmentation fundamentals")
        Test.objects.filter(title="ACT-01 ট্রেনিং টেস্ট").update(title="ACT-01 training test")
        before = counts()
        run()
        self.assertEqual(counts(), before)
        self.assertTrue(Tutorial.objects.filter(title="অ্যাকশন সেগমেন্টেশনের মূল কথা").exists())
        self.assertTrue(Test.objects.filter(title="ACT-01 ট্রেনিং টেস্ট").exists())

    def test_remove_keeps_own_data_and_stays_removed(self, _which):
        own = User.objects.create_superuser(email="owner@example.org", password="x-Strong-123", name="Owner")
        Project.objects.create(name="Our project", slug="our-project", code="OWN-01")
        run()
        out = StringIO()
        call_command("seed_demo", remove=True, stdout=out)
        self.assertEqual(list(User.objects.values_list("email", flat=True)), [own.email])
        self.assertEqual(list(Project.objects.values_list("code", flat=True)), ["OWN-01"])
        for model in (Tutorial, Test, Feedback, PracticeTask, Announcement, Meeting, Guide, QuoteRequest, JobApplication, MediaAsset):
            self.assertFalse(model.objects.exists(), model.__name__)
        self.assertIn("removed on purpose", run(if_outdated=True))
        self.assertFalse(Project.objects.filter(code="ACT-01").exists())

    def test_remove_keeps_the_only_super_admin(self, _which):
        run()
        call_command("seed_demo", remove=True, stdout=StringIO())
        self.assertTrue(User.objects.filter(email="admin@skyleon.local", role=Role.SUPER_ADMIN).exists())


@mock.patch.object(seed_demo.shutil, "which", return_value=None)
class LiveSiteSampleDataTests(TestCase):
    @override_settings(DEBUG=False)
    def test_live_site_needs_own_password_and_uses_own_admin(self, _which):
        with self.assertRaises(CommandError):
            run()
        owner = User.objects.create_superuser(email="owner@example.org", password="x-Strong-123", name="Owner")
        run(password="Sample-Pass-456!")
        self.assertFalse(User.objects.filter(email="admin@skyleon.local").exists())
        self.assertTrue(User.objects.get(email="pm@skyleon.local").check_password("Sample-Pass-456!"))
        self.assertTrue(Tutorial.objects.filter(created_by=owner).exists())

    @override_settings(DEBUG=True, SAMPLE_DATA_AUTO=True)
    def test_preview_tops_up_after_migrate(self, _which):
        from apps.core.signals import top_up_sample_data

        with mock.patch("sys.stdout", new_callable=StringIO), mock.patch("sys.stderr", new_callable=StringIO):
            top_up_sample_data(sender=None)
        self.assertTrue(Project.objects.filter(code="ACT-01").exists())

    @override_settings(DEBUG=False, SAMPLE_DATA_AUTO=True)
    def test_never_on_a_live_site(self, _which):
        from apps.core.signals import top_up_sample_data

        top_up_sample_data(sender=None)
        self.assertFalse(Project.objects.exists())
