"""
Sample data, so every page of the website, the employee portal and the admin panel has something to show.

    python manage.py seed_demo                  # add the full sample set (anything missing — never duplicates)
    python manage.py seed_demo --if-outdated    # only if this database doesn't have the current sample set yet
    python manage.py seed_demo --defaults       # only the tutorial categories (what a live site starts with)
    python manage.py seed_demo --remove         # delete the sample data again (your own data is kept)

Sample accounts use the password given with --password (default Demo@12345 — accepted only while
DEBUG is on; a live site must choose its own). On a live site no extra super admin is created: the
sample content is authored by your own super admin account.

The set is versioned (SAMPLE_VERSION): previews (Codespaces, cloud sessions) top themselves up
automatically when a newer set ships — see apps.core.signals. Items are found by their natural key
(project code, title, e-mail …), so running it again never duplicates anything and never overwrites
what you edited. Items still carrying the first, English version of the sample text are updated
to the current Bangla text.
"""

import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Organization, Role, User, UserStatus
from apps.accounts.services import approve_user
from apps.assessments.models import Question, QuestionOption, QuestionType, Test, TestAttempt, TestKind
from apps.assessments.services import publish_test, start_attempt, submit_attempt
from apps.comms.models import Announcement, AnnouncementRead, Meeting, MeetingInvite
from apps.core.models import Counter
from apps.feedback.models import Feedback
from apps.feedback.services import mark_opened, publish_feedback
from apps.projects.models import Guideline, GuidelineAck, MemberRole, Project, ProjectMember, ProjectStatus, Team
from apps.projects.services import add_member
from apps.storage.backends import get_backend
from apps.storage.models import MediaAsset, MediaKind, MediaStatus
from apps.storage.services import build_key
from apps.training.models import (
    Cadence, OnboardingStep, OnboardingStepType, Tutorial, TutorialCategory, TutorialProgress,
)
from apps.training.services import complete_manual_step, publish_tutorial
from apps.website.models import ContactMessage, JobApplication, QuoteRequest

CATEGORIES = ["Getting started", "Project guidelines", "Annotation techniques", "QA & review", "Tools & platforms", "Daily training"]
SAMPLE_URL = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
DEFAULT_PASSWORD = "Demo@12345"

SAMPLE_VERSION = 2               # bump when the sample set grows; previews then top up by themselves
VERSION_KEY = "sample_data_version"
REMOVED_KEY = "sample_data_removed"

# Identity of every sample item (used by --remove)
SAMPLE_PROJECTS = ["ACT-01", "RTL-02", "PED-03"]
SAMPLE_ORG = "northwind-robotics"
SAMPLE_GUIDE = "sample-clipping-tool-intro"
STAFF = [
    ("admin@skyleon.local", "Ayesha Rahman", Role.SUPER_ADMIN, "Operations Director"),
    ("pm@skyleon.local", "Tanvir Hasan", Role.PROJECT_MANAGER, "Project Manager"),
    ("trainer@skyleon.local", "Nusrat Jahan", Role.TRAINER, "QA Lead & Trainer"),
]
EMPLOYEES = ["Rahim Uddin", "Sadia Islam", "Karim Ahmed", "Farhana Akter", "Imran Hossain", "Mitu Begum", "Jahid Khan", "Shila Roy"]
PENDING = [("new.member1@skyleon.local", "Arif Chowdhury", "Dhaka"), ("new.member2@skyleon.local", "Lina Sarker", "Remote")]
CLIENT = ("client@northwind.example", "Daniel Moore")
LEAD_EMAIL_DOMAINS = ("visionlabs.example", "autonomo.example", "kestrel.example", "soramobility.example",
                      "agrisense.example", "fieldai.example")
APPLICANT_EMAILS = ["rafi.applicant@example.com", "mou.applicant@example.com", "tanjila.applicant@example.com",
                    "sabbir.applicant@example.com"]

# The first (English) version of the sample text — items still carrying it are updated to the Bangla text.
OLD_TITLES = {
    "intro": "Welcome to Skyloon AI — how we work",
    "seg": "Action segmentation fundamentals",
    "desc": "Writing Hand + Action + Object descriptions",
    "daily": "Daily training: occluded hands",
    "cvat": "CVAT shortcuts for bounding boxes",
    "g1": "Action segmentation rules",
    "g2": "Action description format",
    "g_rtl": "Bounding box rules",
    "test_act": "ACT-01 training test",
    "test_fb1": "Feedback #001 check",
    "fb1": "Hand visibility",
    "fb2": "Object naming",
    "ann_qa": "New QA scoring starts Monday",
    "ann_portal": "Welcome to the new training portal",
    "meet_act": "Weekly ACT-01 calibration call",
    "pt1": "Kitchen clip 001 — pick & place",
    "pt2": "Kitchen clip 002 — open & close",
}
OLD_SUMMARIES = {
    "ACT-01": "Segment first-person videos into atomic actions and write Hand + Action + Object descriptions.",
    "RTL-02": "Detect and classify products on store shelf images.",
}
OLD_STEP_TITLES = ["Welcome & project introduction", "Project guidelines video", "Annotation tutorial", "Examples of correct work",
                   "Common mistakes", "QA / review guidelines", "Training test", "Final qualification"]

TRUE_FALSE = lambda answer: [("সত্য", answer), ("মিথ্যা", not answer)]  # noqa: E731


class Command(BaseCommand):
    help = "Add the sample data set (or only the defaults with --defaults, or remove it with --remove)."

    def add_arguments(self, parser):
        parser.add_argument("--defaults", action="store_true", help="Only create the tutorial categories")
        parser.add_argument("--if-outdated", action="store_true", help="Do nothing if this database already has the current sample set")
        parser.add_argument("--remove", action="store_true", help="Delete the sample data (accounts, projects, content, leads)")
        parser.add_argument("--password", default=None, help=f"Password for the sample accounts (default {DEFAULT_PASSWORD}, development only)")

    def handle(self, *args, **opts):
        self.categories = {name: TutorialCategory.objects.get_or_create(name=name, defaults={"slug": name.lower().replace(" & ", "-").replace(" ", "-"), "order": i})[0] for i, name in enumerate(CATEGORIES)}
        if opts["defaults"]:
            self.stdout.write(self.style.SUCCESS("Default tutorial categories ready."))
            return
        if opts["remove"]:
            self.remove()
            return
        if opts["if_outdated"] and marker(REMOVED_KEY):
            self.stdout.write("Sample data was removed on purpose — not adding it again (run seed_demo without --if-outdated to add it).")
            return
        if opts["if_outdated"] and marker(VERSION_KEY) >= SAMPLE_VERSION:
            self.stdout.write("Sample data is up to date.")
            return
        password = opts["password"]
        if not password:
            if not settings.DEBUG:
                raise CommandError(
                    "This is a live site (DEBUG is off): choose the password for the sample accounts yourself, e.g.\n"
                    "  python manage.py seed_demo --password 'Your-Own-Strong-Password'"
                )
            password = DEFAULT_PASSWORD
        # Sample data must never email anyone: queue nothing for immediate delivery and drop the outbox rows.
        from apps.comms.models import EmailMessage

        settings.EMAIL_SEND_IMMEDIATELY = False
        last_email = EmailMessage.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
        self.created = 0
        with transaction.atomic():
            self.seed(password)
            set_marker(VERSION_KEY, SAMPLE_VERSION)
            Counter.objects.filter(key=REMOVED_KEY).delete()
        EmailMessage.objects.filter(pk__gt=last_email).delete()

        self.stdout.write(self.style.SUCCESS(f"Sample data ready ({self.created} new items)."))
        if self.admin.email == STAFF[0][0]:
            self.stdout.write(f"  Super admin:     {STAFF[0][0]} / {password}")
        self.stdout.write(f"  Project manager: pm@skyleon.local / {password}")
        self.stdout.write(f"  Trainer / QA:    trainer@skyleon.local / {password}")
        self.stdout.write(f"  Employees:       employee1..8@skyleon.local / {password}  (waiting for approval: new.member1/2@skyleon.local)")
        self.stdout.write(f"  Client:          {CLIENT[0]} / {password}")

    # ── helpers ─────────────────────────────────────────────────────────────
    def ensure(self, model, key, fields=None, *, old=None, create=None):
        """Find a sample item by `key` — or by `old` (its first English version, which is then updated to the
        current text) — and create it only if neither exists. Returns (obj, created)."""
        fields = fields or {}
        obj = model.objects.filter(**key).first()
        if obj is None and old:
            obj = model.objects.filter(**old).first()
            if obj is not None:
                for k, v in {**key, **fields}.items():
                    setattr(obj, k, v)
                obj.save()
        if obj is not None:
            return obj, False
        self.created += 1
        return (create(**key, **fields) if create else model.objects.create(**key, **fields)), True

    def user(self, email, name, role, password, status=UserStatus.ACTIVE, **extra):
        user = User.objects.filter(email=email).first()
        if user:
            return user
        self.created += 1
        user = User.objects.create_user(email=email, password=password, name=name, role=role, status=UserStatus.PENDING, **extra)
        if role == Role.SUPER_ADMIN:
            user.is_staff = user.is_superuser = True
            user.save()
        if status == UserStatus.ACTIVE:
            approve_user(user, send_email=False)
        return user

    def site_admin(self, password):
        """On a live site the sample content is authored by the site's own super admin (no extra admin account)."""
        if not settings.DEBUG:
            own = User.objects.filter(role=Role.SUPER_ADMIN, is_active=True).exclude(email=STAFF[0][0]).order_by("pk").first()
            if own:
                return own
        email, name, role, title = STAFF[0]
        return self.user(email, name, role, password, title=title)

    def video(self, title, seconds=40, color="0x1a2438"):
        """Generate a small local sample clip with ffmpeg when available, otherwise use a public sample URL."""
        if shutil.which("ffmpeg") and settings.STORAGE_BACKEND == "local":
            key = build_key("tutorial", "sample.webm")
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "sample.webm"
                cmd = [
                    "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=24:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
                    "-vf", f"drawbox=x=0:y=300:w=640:h=60:color={color}@0.85:t=fill",
                    # WebM/VP9 plays in every modern browser (incl. open-source Chromium builds without H.264)
                    "-c:v", "libvpx-vp9", "-b:v", "600k", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus", "-shortest", str(out),
                ]
                try:
                    subprocess.run(cmd, check=True, timeout=120)
                    with open(out, "rb") as fh:
                        size = get_backend().save(key, fh, "video/webm")
                    return MediaAsset.objects.create(
                        kind=MediaKind.VIDEO, provider="local", storage_key=key, mime_type="video/webm", size_bytes=size,
                        duration_sec=float(seconds), width=640, height=360, original_name=f"{title}.webm",
                        status=MediaStatus.READY, purpose="tutorial",
                    )
                except Exception as exc:  # pragma: no cover
                    self.stderr.write(f"ffmpeg failed ({exc}); using sample URL")
        return MediaAsset.objects.create(
            kind=MediaKind.VIDEO, provider="external", external_url=SAMPLE_URL, mime_type="video/mp4", duration_sec=15.0,
            original_name=f"{title}.mp4", status=MediaStatus.READY, purpose="tutorial",
        )

    def tutorial(self, key, title, *, video=None, published_days_ago=0, **fields):
        def create(**kw):
            t = Tutorial.objects.create(video=self.video(*video) if video else None, **kw)
            publish_tutorial(t)
            if published_days_ago:
                Tutorial.objects.filter(pk=t.pk).update(published_at=timezone.now() - timedelta(days=published_days_ago))
            return t
        old = {"title": OLD_TITLES[key]} if key in OLD_TITLES else None
        return self.ensure(Tutorial, {"title": title}, fields, old=old, create=create)[0]

    def test(self, key, title, project, kind, questions, *, passing=80, attempts=3, author=None, publish=True, **extra):
        """A test with its questions. A test still carrying its first English version gets the Bangla text in place
        (same questions and options, so earlier attempts stay valid)."""
        old = Test.objects.filter(title=OLD_TITLES[key], project=project).first() if key in OLD_TITLES else None
        if old and not Test.objects.filter(title=title, project=project).exists():
            old.title, old.description = title, "সব প্রশ্নের উত্তর দিন। স্কোর স্বয়ংক্রিয়ভাবে হিসাব হবে।"
            old.save(update_fields=["title", "description", "updated_at"])
            for q, (prompt, _qtype, options, explanation) in zip(old.questions.order_by("order"), questions):
                Question.objects.filter(pk=q.pk).update(prompt=prompt, explanation=explanation)
                for o, (text, _correct) in zip(q.options.order_by("order"), options):
                    QuestionOption.objects.filter(pk=o.pk).update(text=text)
            return old
        existing = Test.objects.filter(title=title, project=project).first()
        if existing:
            return existing
        self.created += 1
        t = Test.objects.create(title=title, project=project, kind=kind, passing_score=passing, attempt_limit=attempts, created_by=author,
                                description="সব প্রশ্নের উত্তর দিন। স্কোর স্বয়ংক্রিয়ভাবে হিসাব হবে।", **extra)
        for i, (prompt, qtype, options, explanation) in enumerate(questions):
            q = Question.objects.create(test=t, order=i, qtype=qtype, prompt=prompt, explanation=explanation)
            for j, (text, correct) in enumerate(options):
                QuestionOption.objects.create(question=q, order=j, text=text, is_correct=correct)
        if publish:
            publish_test(t)  # assigns it to the project's employees
        return t

    def project(self, code, **fields):
        project = Project.objects.filter(code=code).first()
        if project is None:
            self.created += 1
            return Project.objects.create(code=code, **fields)
        if code in OLD_SUMMARIES and project.summary == OLD_SUMMARIES[code]:
            project.summary, project.description = fields["summary"], fields.get("description", project.description)
            project.save(update_fields=["summary", "description", "updated_at"])
        return project

    def steps(self, project, steps):
        for i, (stype, title, desc, content, rel) in enumerate(steps, start=1):
            step = OnboardingStep.objects.filter(project=project, order=i).first()
            if step is None:
                self.created += 1
                OnboardingStep.objects.create(project=project, order=i, step_type=stype, title=title, description=desc, content=content, **rel)
            elif step.title in OLD_STEP_TITLES:
                step.title, step.description, step.content = title, desc, content
                step.save(update_fields=["title", "description", "content"])

    def watched(self, tutorial, user, days_ago, percent=100):
        p = TutorialProgress.objects.filter(tutorial=tutorial, user=user).first()
        if p is None or p.status == "completed" or p.percent:
            return
        d = (tutorial.video.duration_sec if tutorial.video_id else 0) or 30
        now = timezone.now()
        seen = round(d * percent / 100, 1)
        p.watched_ranges, p.watched_seconds, p.percent, p.last_position_sec = [[0, seen]], seen, percent, seen
        p.first_viewed_at, p.last_viewed_at = now - timedelta(days=days_ago, hours=1), now - timedelta(days=days_ago)
        if percent >= 100:
            p.status, p.completed_at = "completed", now - timedelta(days=days_ago)
        else:
            p.status = "in_progress"
        p.save()

    def answer(self, user, test, wrong=()):
        """Submit an attempt (answers correct except for the question orders in `wrong`) — once per user and test."""
        if not test.is_published or TestAttempt.objects.filter(user=user, test=test).exists():
            return
        attempt = start_attempt(user, test)
        selections = {}
        for q in test.questions.all():
            opts = list(q.options.all())
            pick = [o.pk for o in opts if (not o.is_correct) == (q.order in wrong)]
            selections[str(q.pk)] = pick[:1] if q.order in wrong else pick
        submit_attempt(attempt, selections)

    # ── the sample set ──────────────────────────────────────────────────────
    def seed(self, pw):
        now = timezone.now()
        self.admin = admin = self.site_admin(pw)
        pm = self.user(STAFF[1][0], STAFF[1][1], STAFF[1][2], pw, title=STAFF[1][3])
        trainer = self.user(STAFF[2][0], STAFF[2][1], STAFF[2][2], pw, title=STAFF[2][3])
        employees = [
            self.user(f"employee{i + 1}@skyleon.local", n, Role.EMPLOYEE, pw, title="Annotator", location="Remote", skills=["CVAT", "Video segmentation"])
            for i, n in enumerate(EMPLOYEES)
        ]
        for email, name, location in PENDING:
            self.user(email, name, Role.EMPLOYEE, pw, status=UserStatus.PENDING, location=location)
        org, _ = Organization.objects.get_or_create(slug=SAMPLE_ORG, defaults={"name": "Northwind Robotics", "contact_email": "ops@northwind.example"})
        self.user(CLIENT[0], CLIENT[1], Role.CLIENT, pw, organization=org)

        # ── Projects, teams, members ──
        act = self.project(
            "ACT-01", name="Egocentric Action Segmentation", slug="egocentric-action-segmentation", organization=org,
            client_name="Northwind Robotics", status=ProjectStatus.ACTIVE, color="#088650",
            annotation_type="Video action segmentation + action descriptions", platform="Client annotation server",
            summary="প্রথম-পারসন (egocentric) ভিডিওকে ছোট ছোট অ্যাকশনে ভাগ করা এবং প্রতিটি অংশের জন্য Hand + Action + Object ফরম্যাটে ডেসক্রিপশন লেখা।",
            description="Egocentric ভিডিওর প্রজেক্ট। প্রতিটি ক্লিপ অ্যাকশন বদলানোর জায়গায় ভাগ করা হয়, আর প্রতিটি সেগমেন্টের জন্য নির্দিষ্ট কাঠামোয় একটি ডেসক্রিপশন লেখা হয় (যেমন *Right hand picks up a cup.*)।",
            start_date=(now - timedelta(days=40)).date(),
        )
        rtl = self.project(
            "RTL-02", name="Retail Shelf Detection", slug="retail-shelf-detection", client_name="Confidential retail client",
            status=ProjectStatus.ACTIVE, color="#0d9488", annotation_type="Bounding boxes + product classification", platform="CVAT",
            summary="দোকানের শেলফের ছবিতে প্রতিটি প্রোডাক্টের চারপাশে বক্স আঁকা এবং প্রোডাক্টের ক্যাটাগরি ঠিক করা।",
            start_date=(now - timedelta(days=12)).date(),
        )
        ped = self.project(
            "PED-03", name="Pedestrian Tracking", slug="pedestrian-tracking", client_name="Confidential mobility client",
            status=ProjectStatus.ACTIVE, color="#4d7c0f", annotation_type="Object tracking (video) — boxes + track IDs", platform="CVAT",
            summary="রাস্তার ভিডিওতে প্রতিটি পথচারীকে বক্স দিয়ে চিহ্নিত করা এবং পুরো ভিডিও জুড়ে একই মানুষকে একই track ID দেওয়া।",
            description="নতুন প্রজেক্ট। প্রথম দুই সপ্তাহ ছোট একটা টিম দিয়ে কাজ হবে; মান ঠিক থাকলে টিম বড় করা হবে।",
            start_date=(now - timedelta(days=4)).date(),
        )
        team_a = Team.objects.get_or_create(project=act, name="Team A", defaults={"lead": employees[0]})[0]
        team_b = Team.objects.get_or_create(project=act, name="Team B", defaults={"lead": employees[3]})[0]
        Team.objects.get_or_create(project=ped, name="Pilot team", defaults={"lead": employees[6]})
        add_member(act, pm, role=MemberRole.MANAGER, notify_user=False)
        add_member(act, trainer, role=MemberRole.TRAINER, notify_user=False)
        add_member(rtl, pm, role=MemberRole.MANAGER, notify_user=False)
        add_member(ped, pm, role=MemberRole.MANAGER, notify_user=False)
        add_member(ped, trainer, role=MemberRole.TRAINER, notify_user=False)
        for i, e in enumerate(employees[:6]):
            add_member(act, e, role=MemberRole.REVIEWER if i in (0, 3) else MemberRole.ANNOTATOR, team=team_a if i < 3 else team_b, notify_user=False)
        for e in employees[5:]:
            add_member(rtl, e, notify_user=False)

        # ── Guidelines ──
        g1 = self.ensure(Guideline, {"project": act, "title": "অ্যাকশন সেগমেন্টেশনের নিয়ম"}, {"order": 1, "version": "2.1", "content": (
            "## সেগমেন্টের সীমানা\n\n"
            "- হাত যখন **নতুন একটা অ্যাকশন শুরু করে**, ঠিক তখন নতুন সেগমেন্ট শুরু করুন।\n"
            "- অ্যাকশন **পুরোপুরি শেষ হলে** সেগমেন্ট শেষ করুন (জিনিসটা ছেড়ে দেওয়া হলো, দরজা বন্ধ হলো …)।\n"
            "- **০.৫ সেকেন্ডের** চেয়ে ছোট সেগমেন্ট বানাবেন না।\n\n"
            "## হাত দেখা না গেলে\n\n"
            "হাত যদি **১ সেকেন্ডের বেশি** ফ্রেমের বাইরে থাকে, চলতি সেগমেন্টটা শেষ করুন। "
            "হাত আবার ফ্রেমে ঢুকে কাজ শুরু করলে নতুন সেগমেন্ট শুরু করুন।\n")},
            old={"project": act, "title": OLD_TITLES["g1"]})[0]
        g2 = self.ensure(Guideline, {"project": act, "title": "অ্যাকশন ডেসক্রিপশনের ফরম্যাট"}, {"order": 2, "version": "1.4", "content": (
            "প্রতিটি সেগমেন্টের জন্য একটি ডেসক্রিপশন লিখুন — **Hand + Action + Object** ফরম্যাটে, ইংরেজিতে।\n\n"
            "| সঠিক | ভুল |\n|---|---|\n| Right hand picks up a cup. | Picking cup |\n| Left hand opens the drawer. | hand opens |\n\n"
            "- Present tense ব্যবহার করুন।\n- হাতের নাম লিখুন: *left hand*, *right hand* বা *both hands*।\n"
            "- জিনিসের নির্দিষ্ট নাম লিখুন (*cup* লিখুন, *item* নয়)।")},
            old={"project": act, "title": OLD_TITLES["g2"]})[0]
        g_rtl = self.ensure(Guideline, {"project": rtl, "title": "বাউন্ডিং বক্সের নিয়ম"}, {"order": 1, "content": (
            "- বক্স প্রোডাক্টের দৃশ্যমান কিনারার সাথে **একদম লাগানো (tight)** হবে।\n"
            "- প্রোডাক্টের **৩০%-এর বেশি** দেখা গেলে, আংশিক ঢাকা থাকলেও লেবেল করুন।\n"
            "- ক্যাটালগ মিলিয়ে দেখার পরও না চিনলে তবেই `unknown_product` ক্লাস দিন।")},
            old={"project": rtl, "title": OLD_TITLES["g_rtl"]})[0]
        self.ensure(Guideline, {"project": ped, "title": "ট্র্যাকিংয়ের নিয়ম"}, {"order": 1, "content": (
            "- একই মানুষ পুরো ভিডিওতে **একই track ID** পাবে — কিছুক্ষণ আড়ালে গেলেও।\n"
            "- মানুষটা **২ সেকেন্ডের বেশি** পুরো আড়ালে থাকলে ট্র্যাক থামান; ফিরে এলে একই ID দিয়ে আবার শুরু করুন।\n"
            "- শরীরের **৫০%-এর কম** দেখা গেলে `occluded` অ্যাট্রিবিউট টিক দিন।")})
        # Members of PED-03 are added after its guideline exists, so their onboarding sees it.
        for e in employees[6:]:
            add_member(ped, e, role=MemberRole.TEAM_LEAD if e == employees[6] else MemberRole.ANNOTATOR, notify_user=False)

        # ── Tutorials ──
        cat = self.categories
        t_intro = self.tutorial("intro", "Skyloon AI-তে স্বাগতম — আমরা কীভাবে কাজ করি", video=("welcome", 30), published_days_ago=30,
                                category=cat["Getting started"], cadence=Cadence.ONBOARDING, created_by=admin,
                                description="কোম্পানির পরিচিতি, গোপনীয়তার নিয়ম আর এই পোর্টাল কীভাবে ব্যবহার করবেন।")
        t_privacy = self.tutorial("privacy", "ডেটা গোপনীয়তা ও নিরাপত্তার নিয়ম", published_days_ago=30,
                                  category=cat["Getting started"], cadence=Cadence.ONBOARDING, created_by=admin, description=(
                                      "ক্লায়েন্টের ডেটা আমাদের কাছে আমানত। কাজ শুরুর আগে নিয়মগুলো মন দিয়ে পড়ুন:\n\n"
                                      "1. ক্লায়েন্টের ভিডিও বা ছবি **নিজের ফোন বা কম্পিউটারে ডাউনলোড করবেন না**।\n"
                                      "2. কাজের স্ক্রিনশট বা ভিডিও **কারো সাথে শেয়ার করবেন না** — সোশ্যাল মিডিয়া বা গ্রুপ চ্যাটেও না।\n"
                                      "3. শুধু আপনাকে দেওয়া অ্যাকাউন্ট দিয়ে লগইন করুন; পাসওয়ার্ড কাউকে বলবেন না।\n"
                                      "4. অন্যের কম্পিউটার থেকে কাজ করলে কাজ শেষে অবশ্যই লগআউট করুন।\n"
                                      "5. কোনো কিছু নিয়ে সন্দেহ হলে আগে আপনার প্রজেক্ট ম্যানেজারকে জিজ্ঞেস করুন।"))
        t_seg = self.tutorial("seg", "অ্যাকশন সেগমেন্টেশনের মূল কথা", video=("segmentation", 45, "0x4338ca"), published_days_ago=25,
                              project=act, category=cat["Annotation techniques"], cadence=Cadence.ONBOARDING, created_by=trainer,
                              description="অ্যাকশন কোথায় শুরু আর কোথায় শেষ হয় সেটা খুঁজে বের করা, এক অ্যাকশন থেকে আরেক অ্যাকশনে যাওয়ার মুহূর্ত চেনা, আর অপ্রয়োজনে ছোট ছোট সেগমেন্ট না করা।")
        t_desc = self.tutorial("desc", "Hand + Action + Object ডেসক্রিপশন লেখা", video=("descriptions", 35, "0x0e7490"), published_days_ago=24,
                               project=act, category=cat["Project guidelines"], cadence=Cadence.ONBOARDING, created_by=trainer,
                               description="প্রজেক্টের আসল ধরনের উদাহরণ দেখে নির্দিষ্ট ফরম্যাটে ডেসক্রিপশন লেখা শিখুন।")
        t_daily = self.tutorial("daily", "ডেইলি ট্রেনিং: হাত আংশিক ঢাকা থাকলে", video=("daily-occlusion", 25, "0xbe185d"), published_days_ago=1,
                                project=act, category=cat["Daily training"], cadence=Cadence.DAILY, created_by=trainer,
                                description="আজকের বিষয়: হাত আংশিক লুকানো থাকলে কীভাবে সেগমেন্ট করবেন।")
        t_review = self.tutorial("review", "রিভিউয়াররা কীভাবে আপনার কাজ যাচাই করেন", video=("qa-review", 30, "0x166534"), published_days_ago=20,
                                 project=act, category=cat["QA & review"], cadence=Cadence.REFERENCE, created_by=trainer, is_required=False,
                                 description="QA স্কোর কীভাবে হিসাব হয়, কোন ভুলে কাজ ফেরত আসে, আর রিভিউ কমেন্ট পেলে কী করবেন।")
        t_weekly = self.tutorial("weekly", "সাপ্তাহিক রিভিউ: এই সপ্তাহের সবচেয়ে বেশি হওয়া ভুল", video=("weekly-review", 30, "0x9a3412"), published_days_ago=3,
                                 project=act, category=cat["QA & review"], cadence=Cadence.WEEKLY, created_by=trainer,
                                 description="গত সপ্তাহের রিভিউ থেকে সবচেয়ে বেশি পাওয়া ভুলগুলো, আর প্রতিটির সঠিক উপায়।")
        t_cvat = self.tutorial("cvat", "CVAT-এ বাউন্ডিং বক্সের শর্টকাট", video=("cvat", 30, "0x15803d"), published_days_ago=10,
                               project=rtl, category=cat["Tools & platforms"], cadence=Cadence.REFERENCE, created_by=trainer, is_required=False,
                               description="CVAT-এ দ্রুত বক্স আঁকা আর অ্যাট্রিবিউট বদলানোর কৌশল।")
        t_shelf = self.tutorial("shelf", "শেলফের ছবিতে প্রোডাক্ট চেনা ও বক্স আঁকা", video=("shelf-boxes", 35, "0x0f766e"), published_days_ago=11,
                                project=rtl, category=cat["Annotation techniques"], cadence=Cadence.ONBOARDING, created_by=trainer,
                                description="টাইট বক্স আঁকা, আংশিক ঢাকা প্রোডাক্ট লেবেল করা আর ক্যাটালগ থেকে সঠিক ক্লাস খোঁজা।")
        t_track = self.tutorial("track", "পেডেস্ট্রিয়ান ট্র্যাকিং: একই মানুষ, একই ID", video=("pedestrian-tracking", 40, "0x4d7c0f"), published_days_ago=3,
                                project=ped, category=cat["Annotation techniques"], cadence=Cadence.ONBOARDING, created_by=trainer,
                                description="মানুষটা কিছুক্ষণ আড়ালে গেলেও কীভাবে একই track ID ধরে রাখবেন।")

        # ── Tests ──
        act_test = self.test("test_act", "ACT-01 ট্রেনিং টেস্ট", act, TestKind.ONBOARDING, [
            ("নতুন অ্যাকশন সেগমেন্ট কখন শুরু করবেন?", QuestionType.SINGLE_CHOICE,
             [("হাত যখন নতুন একটা অ্যাকশন শুরু করে", True), ("প্রতি ২ সেকেন্ড পরপর", False), ("ক্যামেরা নড়লে", False)],
             "সেগমেন্ট হাতের অ্যাকশন অনুযায়ী হয় — সময় বা ক্যামেরার নড়াচড়া অনুযায়ী নয়।"),
            ("কোন ডেসক্রিপশনটা প্রজেক্টের ফরম্যাট মেনে লেখা?", QuestionType.SINGLE_CHOICE,
             [("Right hand picks up a cup.", True), ("Picking cup", False), ("cup picked", False)], "Hand + Action + Object, present tense-এ।"),
            ("০.৫ সেকেন্ডের চেয়ে ছোট সেগমেন্ট বানানো যায়।", QuestionType.TRUE_FALSE, TRUE_FALSE(False), "সেগমেন্ট কমপক্ষে ০.৫ সেকেন্ডের হতে হবে।"),
            ("নিচের কোনগুলো সঠিক হাতের লেবেল? (সব সঠিক উত্তর বেছে নিন)", QuestionType.MULTI_SELECT,
             [("Left hand", True), ("Right hand", True), ("Both hands", True), ("Some hand", False)], ""),
        ], passing=75, attempts=3, author=trainer)
        weekly_test = self.test("weekly_test", "সাপ্তাহিক টেস্ট: সেগমেন্টের সীমানা", act, TestKind.TRAINING, [
            ("ড্রয়ার খোলার অ্যাকশন কখন শেষ হয়?", QuestionType.SINGLE_CHOICE,
             [("ড্রয়ার নড়া থামলে", True), ("হাত ড্রয়ারের হাতল ধরলে", False), ("পরের অ্যাকশন শুরু হওয়ার ২ সেকেন্ড পরে", False)],
             "অ্যাকশন পুরোপুরি শেষ হলে — অর্থাৎ ড্রয়ার থেমে গেলে — সেগমেন্ট শেষ।"),
            ("রিভিউয়াররা সীমানার নির্ভুলতা কতটুকু ছাড় দিয়ে মাপেন?", QuestionType.SINGLE_CHOICE,
             [("±৫ ফ্রেম", True), ("±১ সেকেন্ড", False), ("কোনো ছাড় নেই", False)], ""),
            ("নিচের কোন কোন ক্ষেত্রে নতুন সেগমেন্ট শুরু করবেন? (সব সঠিক উত্তর বেছে নিন)", QuestionType.MULTI_SELECT,
             [("হাত নতুন একটা জিনিস ধরতে শুরু করলে", True), ("হাত ১ সেকেন্ডের বেশি বাইরে থেকে ফিরে এসে কাজ শুরু করলে", True),
              ("ক্যামেরা ঘুরে গেলে", False), ("আলো কমে গেলে", False)], ""),
            ("একটা লম্বা অ্যাকশনকে ইচ্ছেমতো কয়েকটা ছোট সেগমেন্টে ভাগ করা যায়।", QuestionType.TRUE_FALSE, TRUE_FALSE(False),
             "অপ্রয়োজনে ভাগ করা (over-segmentation) ভুল হিসেবে ধরা হয়।"),
        ], passing=80, attempts=2, author=trainer, time_limit_min=10)
        rtl_test = self.test("rtl_test", "RTL-02 বাউন্ডিং বক্স টেস্ট", rtl, TestKind.ONBOARDING, [
            ("বাউন্ডিং বক্স কেমন হওয়া উচিত?", QuestionType.SINGLE_CHOICE,
             [("প্রোডাক্টের দৃশ্যমান কিনারার সাথে একদম লাগানো", True), ("চারপাশে কিছুটা ফাঁকা রেখে", False), ("পুরো শেলফ জুড়ে", False)], ""),
            ("একটা প্রোডাক্টের ৪০% দেখা যাচ্ছে। কী করবেন?", QuestionType.SINGLE_CHOICE,
             [("লেবেল করব", True), ("বাদ দেব", False), ("unknown_product দেব", False)], "৩০%-এর বেশি দেখা গেলে লেবেল করতে হয়।"),
            ("ক্যাটালগ না দেখেই unknown_product ক্লাস দেওয়া যায়।", QuestionType.TRUE_FALSE, TRUE_FALSE(False),
             "আগে ক্যাটালগে খুঁজতে হবে; না পেলে তবেই unknown_product।"),
        ], passing=70, attempts=3, author=trainer)
        self.test("qual_test", "ACT-01 ফাইনাল কোয়ালিফিকেশন টেস্ট", act, TestKind.QUALIFICATION, [
            ("হাত ফ্রেমের বাইরে ৩ সেকেন্ড থেকে ফিরে এসে একই কাপ ধরল। কয়টা সেগমেন্ট হবে?", QuestionType.SINGLE_CHOICE,
             [("দুটো — ফাঁকের আগে একটা, পরে একটা", True), ("একটা লম্বা সেগমেন্ট", False), ("তিনটা", False)], ""),
            ("“Right hand puts the cup on the table.” — ডেসক্রিপশনটা কি ফরম্যাট মেনে লেখা?", QuestionType.TRUE_FALSE, TRUE_FALSE(True), ""),
        ], passing=90, attempts=1, author=trainer, publish=False)  # still a draft: shows how drafts look in the admin panel

        # ── Onboarding paths ──
        self.steps(act, [
            (OnboardingStepType.WELCOME, "স্বাগতম ও প্রজেক্ট পরিচিতি", "প্রজেক্ট আর তার লক্ষ্য সম্পর্কে জানুন।",
             "**ACT-01**-এ স্বাগতম! এখানে আপনি egocentric ভিডিওকে ছোট ছোট অ্যাকশনে ভাগ করবেন এবং প্রতিটি সেগমেন্টের জন্য একটি ডেসক্রিপশন লিখবেন।", {}),
            (OnboardingStepType.GUIDELINE_VIDEO, "প্রজেক্ট গাইডলাইনের ভিডিও", "কোম্পানির পরিচিতি ভিডিওটা দেখুন।", "", {"tutorial": t_intro}),
            (OnboardingStepType.TUTORIAL, "অ্যানোটেশন টিউটোরিয়াল", "অ্যাকশন সেগমেন্টেশন শিখুন।", "", {"tutorial": t_seg}),
            (OnboardingStepType.EXAMPLES, "সঠিক কাজের উদাহরণ", "গ্রহণযোগ্য সেগমেন্টগুলো দেখে নিন।",
             "- *Right hand picks up a cup.* — আঙুল কাপের ওপর বন্ধ হতে শুরু করলেই সেগমেন্ট শুরু।\n"
             "- *Left hand opens the drawer.* — ড্রয়ার থেমে গেলে সেগমেন্ট শেষ।", {"guideline": g2}),
            (OnboardingStepType.COMMON_MISTAKES, "সাধারণ ভুলগুলো", "যে কারণে কাজ সবচেয়ে বেশি ফেরত আসে।",
             "1. সেগমেন্ট দেরিতে শুরু হওয়া।\n2. ভুল হাতের নাম লেখা।\n3. জিনিসের অস্পষ্ট নাম (\"item\")।\n4. হাত ফ্রেমে ফিরে আসার পর সেগমেন্ট বাদ পড়ে যাওয়া।", {}),
            (OnboardingStepType.QA_GUIDELINES, "QA / রিভিউয়ের নিয়ম", "রিভিউয়াররা আপনার কাজ কীভাবে স্কোর করেন।",
             "রিভিউয়াররা দেখেন: সীমানা ঠিক আছে কিনা (±৫ ফ্রেম), হাত / অ্যাকশন / জিনিস মিলছে কিনা, আর গাইডলাইন মানা হয়েছে কিনা।", {"guideline": g1}),
            (OnboardingStepType.TEST, "ট্রেনিং টেস্ট", "৭৫% বা তার বেশি পেয়ে পাস করুন।", "", {"test": act_test}),
            (OnboardingStepType.QUALIFICATION, "ফাইনাল কোয়ালিফিকেশন", "আপনার ম্যানেজার একটা নমুনা ব্যাচ রিভিউ করবেন।",
             "টেস্টে পাস করার পর ২০টি ক্লিপের একটা নমুনা ব্যাচ শেষ করুন। তারপর প্রজেক্ট ম্যানেজার আপনাকে প্রোডাকশনের জন্য অনুমোদন দেবেন।", {}),
        ])
        self.steps(rtl, [
            (OnboardingStepType.WELCOME, "স্বাগতম ও প্রজেক্ট পরিচিতি", "RTL-02 প্রজেক্ট সম্পর্কে জানুন।",
             "**RTL-02**-এ আপনি দোকানের শেলফের ছবিতে প্রোডাক্টের চারপাশে বক্স আঁকবেন এবং প্রতিটি প্রোডাক্টের ক্লাস ঠিক করবেন।", {}),
            (OnboardingStepType.TUTORIAL, "অ্যানোটেশন টিউটোরিয়াল", "টাইট বক্স আঁকা শিখুন।", "", {"tutorial": t_shelf}),
            (OnboardingStepType.QA_GUIDELINES, "বাউন্ডিং বক্সের নিয়ম", "নিয়মগুলো পড়ে নিশ্চিত করুন।", "", {"guideline": g_rtl}),
            (OnboardingStepType.TEST, "ট্রেনিং টেস্ট", "৭০% বা তার বেশি পেয়ে পাস করুন।", "", {"test": rtl_test}),
        ])

        # ── Feedback ──
        def feedback(key, topic, project, fields, *, video=None, test=None, days_ago=0):
            def create(**kw):
                fb = Feedback.objects.create(video=self.video(*video) if video else None, test=test, **kw)
                publish_feedback(fb)
                if days_ago:
                    Feedback.objects.filter(pk=fb.pk).update(published_at=timezone.now() - timedelta(days=days_ago))
                return fb
            old = {"topic": OLD_TITLES[key], "project": project} if key in OLD_TITLES else None
            return self.ensure(Feedback, {"topic": topic, "project": project}, fields, old=old, create=create)[0]

        fb1_test = self.test("test_fb1", "ফিডব্যাক #001 যাচাই", act, TestKind.FEEDBACK, [
            ("হাত ২ সেকেন্ডের জন্য ফ্রেমের বাইরে চলে গেল। আপনি কী করবেন?", QuestionType.SINGLE_CHOICE,
             [("চলতি সেগমেন্ট শেষ করব, হাত ফিরে এলে নতুন সেগমেন্ট শুরু করব", True), ("একটাই লম্বা সেগমেন্ট রাখব", False), ("ক্লিপটা মুছে দেব", False)],
             "গাইডলাইন দেখুন: হাত দেখা না গেলে।"),
            ("শুধু আঙুল দেখা গেলেও (হাত আংশিক দেখা গেলে) হাতকে দৃশ্যমান ধরা হয়।", QuestionType.TRUE_FALSE, TRUE_FALSE(True),
             "অ্যাকশনটা বোঝা গেলে হাত দৃশ্যমান ধরা হয়।"),
        ], passing=100, attempts=2, author=trainer, publish=False)
        fb1 = feedback("fb1", "হাত ফ্রেমের বাইরে গেলে", act, {
            "summary": "হাত ফ্রেমের বাইরে থাকার সময়ও কয়েকটা সেগমেন্ট চলতে থেকেছে।", "severity": "important", "created_by": trainer,
            "explanation": ("হাত **১ সেকেন্ডের বেশি ফ্রেমের বাইরে** গেলে চলতি সেগমেন্টটা শেষ করুন। হাত আবার ফ্রেমে ঢুকে কাজ শুরু করলে নতুন সেগমেন্ট শুরু করুন।\n\n"
                            "**সঠিক:** ফাঁকের দুই পাশে দুটো আলাদা সেগমেন্ট।\n**ভুল:** ফাঁকসহ পুরোটা জুড়ে একটা লম্বা সেগমেন্ট।"),
        }, video=("feedback-hand-visibility", 30, "0xb45309"), test=fb1_test, days_ago=6)
        feedback("fb2", "অবজেক্টের নাম", act, {
            "team": team_b, "cadence": "weekly", "created_by": trainer, "summary": "জিনিসের নির্দিষ্ট নাম লিখুন।",
            "explanation": "*cup*, *bottle*, *drawer* — এভাবে নির্দিষ্ট নাম লিখুন। কখনো *item* বা *thing* লিখবেন না।",
        }, days_ago=4)
        fb3_test = self.test("test_fb3", "ফিডব্যাক: সেগমেন্টের শুরু যাচাই", act, TestKind.FEEDBACK, [
            ("সেগমেন্টের শুরু কোথায় হওয়া উচিত?", QuestionType.SINGLE_CHOICE,
             [("হাত যখন অ্যাকশনটা শুরু করে — জিনিসটার দিকে এগোতে শুরু করে", True), ("জিনিসটা হাতে ওঠার পরে", False), ("অ্যাকশনের মাঝামাঝি", False)], ""),
            ("সেগমেন্ট ±৫ ফ্রেমের বেশি দেরিতে শুরু হলে রিভিউতে সেটা ভুল ধরা হয়।", QuestionType.TRUE_FALSE, TRUE_FALSE(True), ""),
        ], passing=100, attempts=2, author=trainer, publish=False)
        fb3 = feedback("fb3", "সেগমেন্ট দেরিতে শুরু হচ্ছে", act, {
            "severity": "critical", "created_by": trainer,
            "summary": "অনেক সেগমেন্ট শুরু হচ্ছে জিনিসটা হাতে ওঠার পরে — অ্যাকশনের শুরুতে নয়।",
            "explanation": ("সেগমেন্ট শুরু হবে **যে মুহূর্তে হাত অ্যাকশনটা শুরু করে** — যেমন কাপের দিকে হাত এগোতে শুরু করলেই। "
                            "কাপ হাতে ওঠার পর শুরু করলে অ্যাকশনের প্রথম অংশ বাদ পড়ে যায়।\n\n"
                            "রিভিউয়াররা সীমানায় **±৫ ফ্রেম** পর্যন্ত ছাড় দেন — এর বেশি দেরি হলে ভুল ধরা হবে।"),
        }, video=("feedback-late-start", 30, "0x991b1b"), test=fb3_test, days_ago=1)
        feedback("fb4", "বক্স টাইট হচ্ছে না", rtl, {
            "created_by": trainer, "summary": "অনেক বক্সের চারপাশে বাড়তি ফাঁকা জায়গা থাকছে।",
            "explanation": "বক্সের প্রতিটি কিনারা প্রোডাক্টের **দৃশ্যমান কিনারার সাথে মিলিয়ে** দিন। বক্স আঁকার পর জুম করে চারদিক একবার মিলিয়ে নিন।",
        }, video=("feedback-loose-boxes", 25, "0x0f766e"), days_ago=2)

        # ── Practice Lab ──
        from apps.practice.models import PracticeAttempt, PracticeTask
        from apps.practice.services import get_draft, save_draft, submit

        def fit(video, design_len, rng, clips):
            """Scale a segmentation designed for a `design_len`-second clip to the real video length."""
            k = min(1.0, (video.duration_sec or design_len) / design_len)
            return dict(range_start=round(rng[0] * k, 2), range_end=round(rng[1] * k, 2),
                        reference_clips=[[round(a * k, 2), round(b * k, 2)] for a, b in clips])

        practice = []
        for i, (key, title, tutorial, design, rng, clips, text) in enumerate([
            ("pt1", "কিচেন ক্লিপ ০০১ — তোলা ও রাখা", t_seg, 45, (3, 40), [[4.0, 7.5], [8.0, 12.0], [12.5, 18.0], [19.0, 24.5], [25.0, 31.0], [32.0, 39.5]],
             "হাত দেখা যাওয়ার অংশে প্রতিটি হাতের অ্যাকশন আলাদা ক্লিপ করুন। হাত অ্যাকশন শুরু করলে ক্লিপ শুরু করুন, অ্যাকশন শেষ হলে ক্লিপ শেষ করুন।"),
            ("pt2", "কিচেন ক্লিপ ০০২ — খোলা ও বন্ধ করা", t_desc, 35, (2, 33), [[3.0, 6.0], [7.0, 11.5], [12.0, 17.0], [18.5, 24.0], [25.0, 32.0]],
             "প্রতিটি খোলা / বন্ধ করার অ্যাকশন আলাদা ক্লিপ করুন। মনে রাখবেন: দরজা বা ড্রয়ার নড়া থামলে তবেই ক্লিপ শেষ।"),
            ("pt3", "কিচেন ক্লিপ ০০৩ — হাত আংশিক ঢাকা", t_daily, 25, (1, 24), [[1.5, 5.0], [5.5, 9.0], [11.0, 15.5], [16.0, 20.0], [20.5, 23.5]],
             "হাত আংশিক ঢাকা থাকলেও অ্যাকশন বোঝা গেলে ক্লিপ করুন। হাত ১ সেকেন্ডের বেশি ফ্রেমের বাইরে গেলে ক্লিপ ভেঙে দিন।"),
        ]):
            task = self.ensure(
                PracticeTask, {"title": title}, {"instructions": text},
                old={"title": OLD_TITLES[key]} if key in OLD_TITLES else None,
                create=lambda tutorial=tutorial, design=design, rng=rng, clips=clips, order=i, **kw: PracticeTask.objects.create(
                    project=act, video=tutorial.video, tolerance_sec=0.5, passing_score=75, status="published", published_at=timezone.now(),
                    created_by=trainer, order=order, **fit(tutorial.video, design, rng, clips), **kw),
            )[0]
            practice.append(task)

        def practise(user, task, shift=0.0, drop=None, minutes=6):
            if PracticeAttempt.objects.filter(user=user, task=task).exists() or not task.reference_clips:
                return
            clips = [[round(a + shift, 2), round(b + shift, 2)] for j, (a, b) in enumerate(task.reference_clips) if j != drop]
            submit(get_draft(task, user), clips, time_spent=minutes * 60)

        # ── Work guide (sample — the real guides are built from the original documents) ──
        import json

        from apps.guides.importer import import_guide
        from apps.guides.models import Guide, GuideProgress, GuideStep

        sample = Path(__file__).resolve().parents[3] / "guides" / "fixtures" / "sample_guide.json"
        if sample.exists() and not Guide.objects.filter(slug=SAMPLE_GUIDE).exists():
            self.created += 1
            import_guide(json.loads(sample.read_text(encoding="utf-8")), publish=True, user=trainer)

        # ── Announcements & meetings ──
        def announce(key, title, body, *, project=None, author=pm, priority="normal", pinned=False, days_ago=0):
            ann, created = self.ensure(Announcement, {"title": title}, {"body": body, "project": project, "priority": priority, "pinned": pinned},
                                       old={"title": OLD_TITLES[key]} if key in OLD_TITLES else None,
                                       create=lambda **kw: Announcement.objects.create(created_by=author, **kw))
            if created and days_ago:
                Announcement.objects.filter(pk=ann.pk).update(published_at=timezone.now() - timedelta(days=days_ago))
            return ann

        ann_portal = announce("ann_portal", "নতুন ট্রেনিং পোর্টালে স্বাগতম",
                              "সব ট্রেনিং ভিডিও, ফিডব্যাক আর টেস্ট এখন এই পোর্টালে। আপনার অগ্রগতি স্বয়ংক্রিয়ভাবে রেকর্ড হয়।",
                              author=admin, days_ago=14)
        ann_qa = announce("ann_qa", "সোমবার থেকে নতুন QA স্কোরিং",
                          "**সোমবার** থেকে রিভিউয়াররা সেগমেন্টের সীমানা **±৫ ফ্রেম** ছাড় দিয়ে স্কোর করবেন। তার আগে *অ্যাকশন সেগমেন্টেশনের নিয়ম* গাইডলাইনটা আরেকবার পড়ে নিন।",
                          project=act, priority="important", pinned=True, days_ago=2)
        announce("ann_lab", "প্র্যাকটিস ল্যাব চালু হয়েছে",
                 "আসল ক্লিপিং টুলের মতো দেখতে **প্র্যাকটিস ল্যাব** এখন পোর্টালে আছে। এখানে যতবার খুশি অনুশীলন করুন — প্রতিবার স্কোর আর কোথায় ভুল হয়েছে সেটা দেখতে পাবেন।",
                 author=trainer, days_ago=5)
        announce("ann_rtl", "RTL-02: প্রোডাক্ট ক্যাটালগের নতুন সংস্করণ",
                 "প্রোডাক্ট ক্যাটালগের নতুন সংস্করণ যোগ হয়েছে। `unknown_product` দেওয়ার আগে অবশ্যই নতুন ক্যাটালগে খুঁজে দেখুন।",
                 project=rtl, days_ago=3)
        announce("ann_ped", "PED-03 প্রজেক্ট শুরু হচ্ছে",
                 "নতুন **Pedestrian Tracking (PED-03)** প্রজেক্টে আপনাকে যোগ করা হয়েছে। কাজ শুরুর আগে ট্র্যাকিংয়ের নিয়ম আর ট্রেনিং ভিডিওটা দেখে নিন।",
                 project=ped, priority="important")

        def meeting(key, title, starts_at, invitees, **fields):
            m, created = self.ensure(Meeting, {"title": title}, fields, old={"title": OLD_TITLES[key]} if key in OLD_TITLES else None,
                                     create=lambda **kw: Meeting.objects.create(created_by=pm, starts_at=starts_at, **kw))
            for u in invitees:
                MeetingInvite.objects.get_or_create(meeting=m, user=u)
            return m

        meeting("meet_act", "ACT-01 সাপ্তাহিক ক্যালিব্রেশন কল", now + timedelta(days=2, hours=3), employees[:6], project=act, duration_min=45,
                meeting_url="https://meet.google.com/abc-defg-hij", agenda="ফিডব্যাকের সাধারণ ভুলগুলো নিয়ে আলোচনা আর কয়েকটা কঠিন ক্লিপ একসাথে দেখা।")
        meeting("meet_new", "নতুন সদস্যদের পরিচিতি সেশন", now + timedelta(days=5, hours=1), employees, duration_min=60,
                meeting_url="https://meet.google.com/xyz-abcd-efg", agenda="পোর্টাল ব্যবহার, ট্রেনিংয়ের ধাপ আর কাজের নিয়ম নিয়ে পরিচিতি। প্রশ্ন থাকলে সাথে নিয়ে আসুন।")
        meeting("meet_rtl", "RTL-02 QA রিভিউ মিটিং", now - timedelta(days=3), employees[5:], project=rtl, duration_min=30,
                meeting_url="https://meet.google.com/qrs-tuvw-xyz", agenda="গত সপ্তাহের রিভিউ ফলাফল আর বক্স টাইট না হওয়ার ভুল নিয়ে আলোচনা।")
        meeting("meet_ped", "PED-03 কিক-অফ মিটিং", now + timedelta(days=1, hours=2), employees[6:] + [trainer], project=ped, duration_min=30,
                meeting_url="https://meet.google.com/ped-kick-off", agenda="প্রজেক্টের লক্ষ্য, টুল আর প্রথম সপ্তাহের কাজের পরিকল্পনা।")

        # ── Activity: what employees have already done ──
        for i, e in enumerate(employees[:6]):
            self.watched(t_intro, e, 6 - i % 3)
            self.watched(t_privacy, e, 6 - i % 3)
            if i < 4:
                self.watched(t_seg, e, 5 - i % 3)
                self.watched(t_desc, e, 4 - i % 2)
                self.answer(e, act_test, wrong=(0,) if i == 3 else ())
                for g in (g1, g2):
                    GuidelineAck.objects.get_or_create(guideline=g, user=e, defaults={"version": g.version})
            elif i == 4:
                self.watched(t_seg, e, 1, percent=60)
            if i < 2:
                self.watched(t_daily, e, 0)
                self.watched(t_weekly, e, 1)
                self.answer(e, weekly_test, wrong=(2,) if i == 1 else ())
            rec = fb1.recipients.filter(user=e).first()
            if rec and i < 3 and not rec.watched_at:
                mark_opened(rec, has_video=True)
                rec.watched_at, rec.percent = now - timedelta(hours=10 - i), 100
                rec.save()
                self.answer(e, fb1_test, wrong=(0, 1) if i == 2 else ())
            rec = fb3.recipients.filter(user=e).first()
            if rec and i == 0 and not rec.first_viewed_at:
                mark_opened(rec, has_video=True)
        for e in employees[5:]:
            self.watched(t_intro, e, 3)
            self.watched(t_shelf, e, 2)
            self.answer(e, rtl_test, wrong=(1,) if e == employees[7] else ())
        self.watched(t_track, employees[6], 0, percent=45)

        for step in OnboardingStep.objects.filter(project=act):
            for e in employees[:2]:
                complete_manual_step(step, e)
        if ProjectMember.objects.filter(project=act, user__in=employees[:2], qualified_at__isnull=True).exists():
            ProjectMember.objects.filter(project=act, user__in=employees[:2]).update(qualified_at=now - timedelta(days=2), qualified_by=pm)

        for i, e in enumerate(employees[:4]):
            practise(e, practice[0], shift=(0.0, 0.2, 0.4, 0.9)[i], drop=2 if i == 2 else None, minutes=5 + i)
        for i, e in enumerate(employees[:2]):
            practise(e, practice[1], shift=(0.1, 0.6)[i], minutes=4 + i)
        if not PracticeAttempt.objects.filter(user=employees[4]).exists() and practice[0].reference_clips:
            save_draft(get_draft(practice[0], employees[4]), practice[0].reference_clips[:2], time_spent=120)

        guide_steps = list(GuideStep.objects.filter(guide__slug=SAMPLE_GUIDE).order_by("section__order", "order"))
        for e, upto in ((employees[0], len(guide_steps)), (employees[1], 2), (employees[2], 1)):
            for s in guide_steps[:upto]:
                GuideProgress.objects.get_or_create(user=e, step=s)

        for e in employees[:5]:
            AnnouncementRead.objects.get_or_create(announcement=ann_portal, user=e)
        for e in employees[:2]:
            AnnouncementRead.objects.get_or_create(announcement=ann_qa, user=e)

        # ── Website enquiries (admin panel → Leads / Applications) ──
        leads = [
            dict(name="Emily Carter", company="Vision Labs", email="emily@visionlabs.example", project_type="Video annotation",
                 annotation_types=["Action segmentation", "Object tracking"], dataset_size="5,000 videos (~800 hours)", timeline="3 months",
                 platform="Client-provided platform", requirements="Egocentric kitchen videos; need action segments with structured descriptions."),
            dict(name="Lukas Weber", company="Autonomo GmbH", email="lukas@autonomo.example", project_type="Image annotation",
                 annotation_types=["Bounding boxes", "Semantic segmentation"], dataset_size="120k images", timeline="6 weeks", platform="CVAT", status="contacted"),
            dict(name="Sofia Martins", company="Kestrel Robotics", email="sofia@kestrel.example", project_type="Video annotation",
                 annotation_types=["Object tracking", "Keypoint annotation"], dataset_size="300 hours of warehouse footage",
                 timeline="Pilot first, then ongoing", platform="Their own web tool", status="qualified",
                 requirements="Start with a 10-hour pilot; track IDs must stay consistent through occlusions."),
            dict(name="Hiro Tanaka", company="Sora Mobility", email="hiro@soramobility.example", project_type="Image annotation",
                 annotation_types=["Polygon segmentation"], dataset_size="40k street images", timeline="8 weeks", platform="CVAT",
                 status="proposal", notes="Proposal sent — waiting for their feedback on pricing."),
        ]
        for lead in leads:
            self.ensure(QuoteRequest, {"email": lead.pop("email")}, lead)
        self.ensure(ContactMessage, {"email": "priya@agrisense.example"}, dict(
            name="Priya Nair", company="AgriSense", subject="Crop annotation pilot", message="We'd like to discuss a pilot for fruit detection and counting."))
        self.ensure(ContactMessage, {"email": "jonas@fieldai.example"}, dict(
            name="Jonas Becker", company="FieldAI", subject="Annotation for drone imagery", status="contacted",
            message="Do you handle aerial images with very small objects? We'd like to know the turnaround for about 5,000 images."))
        applicants = [
            dict(full_name="Rafi Islam", phone="+8801700000000", location="Chattogram", experience="1 – 2 years",
                 annotation_experience="Bounding boxes and polygons in CVAT for a retail project.", preferred_work_type="Remote — full-time",
                 availability="Immediately", skills=["CVAT", "Polygon", "Bounding boxes"]),
            dict(full_name="Mou Akter", phone="+8801800000000", location="Remote", experience="No professional experience yet",
                 preferred_work_type="Remote — part-time", availability="Within 1 week", skills=["Excel"]),
            dict(full_name="Tanjila Ahmed", phone="+8801900000000", location="Khulna", experience="Less than 6 months",
                 annotation_experience="Image classification tasks on a freelance platform.", preferred_work_type="Remote — full-time",
                 availability="Within 2 weeks", skills=["Image classification", "Excel"], status="shortlisted"),
            dict(full_name="Sabbir Hossain", phone="+8801600000000", location="Rajshahi", experience="More than 2 years",
                 annotation_experience="Video segmentation and polygon annotation for driving datasets.", preferred_work_type="Contract / project-based",
                 availability="Within 1 month", skills=["Video segmentation", "Polygon", "CVAT"], status="reviewing"),
        ]
        for email, data in zip(APPLICANT_EMAILS, applicants):
            self.ensure(JobApplication, {"email": email}, data)

    # ── --remove ────────────────────────────────────────────────────────────
    def remove(self):
        from apps.feedback.models import Feedback as Fb
        from apps.guides.models import Guide
        from apps.practice.models import PracticeTask
        from apps.storage.services import delete_asset

        projects = Project.objects.filter(code__in=SAMPLE_PROJECTS)
        sample_users = User.objects.filter(email__in=[s[0] for s in STAFF[1:]] + [f"employee{i + 1}@skyleon.local" for i in range(len(EMPLOYEES))]
                                           + [p[0] for p in PENDING] + [CLIENT[0]])
        demo_admin = User.objects.filter(email=STAFF[0][0])
        keep_admin = not User.objects.filter(role=Role.SUPER_ADMIN, is_active=True).exclude(email=STAFF[0][0]).exists()

        # Videos made for the sample content (deleted with their files once nothing uses them)
        videos = set(Tutorial.objects.filter(project__in=projects).values_list("video_id", flat=True))
        videos |= set(Fb.objects.filter(project__in=projects).values_list("video_id", flat=True))
        videos |= set(PracticeTask.objects.filter(project__in=projects).values_list("video_id", flat=True))
        company_titles = ["Skyloon AI-তে স্বাগতম — আমরা কীভাবে কাজ করি", "ডেটা গোপনীয়তা ও নিরাপত্তার নিয়ম", OLD_TITLES["intro"]]
        company = Tutorial.objects.filter(project__isnull=True, title__in=company_titles)
        videos |= set(company.values_list("video_id", flat=True))
        videos.discard(None)

        counts = {
            "projects (with their tutorials, tests, feedback, practice tasks)": projects.count(),
            "company-wide tutorials": company.count(),
        }
        with transaction.atomic():
            Meeting.objects.filter(project__in=projects).delete()
            Meeting.objects.filter(project__isnull=True, title="নতুন সদস্যদের পরিচিতি সেশন").delete()
            Announcement.objects.filter(project__isnull=True, title__in=[
                "নতুন ট্রেনিং পোর্টালে স্বাগতম", "প্র্যাকটিস ল্যাব চালু হয়েছে", OLD_TITLES["ann_portal"]]).delete()
            Guide.objects.filter(slug=SAMPLE_GUIDE).delete()
            company.delete()
            projects.delete()
            counts["accounts"] = sample_users.count() + (0 if keep_admin else demo_admin.count())
            sample_users.delete()
            if not keep_admin:
                demo_admin.delete()
            Organization.objects.filter(slug=SAMPLE_ORG, users__isnull=True).delete()
            leads = QuoteRequest.objects.none()
            for domain in LEAD_EMAIL_DOMAINS:
                leads = leads | QuoteRequest.objects.filter(email__iendswith="@" + domain)
            counts["quote requests"] = leads.count()
            leads.delete()
            contacts = ContactMessage.objects.filter(email__in=["priya@agrisense.example", "jonas@fieldai.example"])
            counts["contact messages"] = contacts.count()
            contacts.delete()
            apps_qs = JobApplication.objects.filter(email__in=APPLICANT_EMAILS)
            counts["job applications"] = apps_qs.count()
            apps_qs.delete()
            set_marker(REMOVED_KEY, 1)
            Counter.objects.filter(key=VERSION_KEY).delete()
        used = _used_assets(videos)
        for asset in MediaAsset.objects.filter(pk__in=videos - used):
            delete_asset(asset)

        self.stdout.write(self.style.SUCCESS("Sample data removed."))
        for label, n in counts.items():
            self.stdout.write(f"  {n:>3}  {label}")
        if keep_admin and demo_admin.exists():
            self.stdout.write(f"  Kept {STAFF[0][0]} — it is the only super admin. Create your own (python manage.py createsuperuser), then run this again.")
        self.stdout.write("  It is not added back automatically; run `python manage.py seed_demo` to add it again.")


def marker(key) -> int:
    return Counter.objects.filter(key=key).values_list("value", flat=True).first() or 0


def set_marker(key, value) -> None:
    Counter.objects.update_or_create(key=key, defaults={"value": value})


def _used_assets(ids) -> set:
    """Which of these media assets are still referenced by something that stays."""
    from apps.feedback.models import Feedback as Fb
    from apps.guides.models import GuideStep, GuideTaskError
    from apps.practice.models import PracticeTask

    used = set()
    for model, field in ((Tutorial, "video_id"), (Fb, "video_id"), (PracticeTask, "video_id"),
                         (GuideStep, "video_asset_id"), (GuideTaskError, "video_asset_id")):
        used |= set(model.objects.filter(**{f"{field}__in": ids}).values_list(field, flat=True))
    return used
