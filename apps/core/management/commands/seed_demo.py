"""
Demo / starter data.

    python manage.py seed_demo              # full demo dataset (staff, employees, projects, content)
    python manage.py seed_demo --defaults   # only tutorial categories (safe for production)

Demo accounts all use the password given with --password (default: Demo@12345).
"""

import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Organization, Role, User, UserStatus
from apps.accounts.services import approve_user
from apps.assessments.models import Question, QuestionOption, QuestionType, Test, TestKind
from apps.assessments.services import publish_test, start_attempt, submit_attempt
from apps.comms.models import Announcement, Meeting, MeetingInvite
from apps.core.choices import ContentStatus
from apps.feedback.models import Feedback
from apps.feedback.services import mark_opened, publish_feedback
from apps.projects.models import Guideline, MemberRole, Project, ProjectStatus, Team
from apps.projects.services import add_member
from apps.storage.backends import get_backend
from apps.storage.models import MediaAsset, MediaKind, MediaStatus
from apps.storage.services import build_key
from apps.training.models import Cadence, OnboardingStep, OnboardingStepType, Tutorial, TutorialCategory, TutorialProgress
from apps.training.services import publish_tutorial
from apps.website.models import ContactMessage, JobApplication, QuoteRequest

CATEGORIES = ["Getting started", "Project guidelines", "Annotation techniques", "QA & review", "Tools & platforms", "Daily training"]
SAMPLE_URL = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"


class Command(BaseCommand):
    help = "Create demo data (or only defaults with --defaults)."

    def add_arguments(self, parser):
        parser.add_argument("--defaults", action="store_true", help="Only create tutorial categories")
        parser.add_argument("--password", default="Demo@12345")

    def handle(self, *args, **opts):
        self.categories = {name: TutorialCategory.objects.get_or_create(name=name, defaults={"slug": name.lower().replace(" & ", "-").replace(" ", "-"), "order": i})[0] for i, name in enumerate(CATEGORIES)}
        if opts["defaults"]:
            self.stdout.write(self.style.SUCCESS("Default tutorial categories ready."))
            return
        # Demo data must never email anyone: queue nothing for immediate delivery and drop the outbox rows.
        from apps.comms.models import EmailMessage

        settings.EMAIL_SEND_IMMEDIATELY = False
        last_email = EmailMessage.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
        with transaction.atomic():
            self.seed(opts["password"])
        EmailMessage.objects.filter(pk__gt=last_email).delete()

    # ------------------------------------------------------------------
    def user(self, email, name, role, password, status=UserStatus.ACTIVE, **extra):
        user = User.objects.filter(email=email).first()
        if user:
            return user
        user = User.objects.create_user(email=email, password=password, name=name, role=role, status=UserStatus.PENDING, **extra)
        if role == Role.SUPER_ADMIN:
            user.is_staff = user.is_superuser = True
            user.save()
        if status == UserStatus.ACTIVE:
            approve_user(user, send_email=False)
        return user

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

    def test(self, title, project, kind, questions, passing=80, attempts=3, author=None):
        t = Test.objects.create(title=title, project=project, kind=kind, passing_score=passing, attempt_limit=attempts,
                                description="Answer all questions. Your score is calculated automatically.", created_by=author)
        for i, (prompt, qtype, options, explanation) in enumerate(questions):
            q = Question.objects.create(test=t, order=i, qtype=qtype, prompt=prompt, explanation=explanation)
            for j, (text, correct) in enumerate(options):
                QuestionOption.objects.create(question=q, order=j, text=text, is_correct=correct)
        return t

    def seed(self, pw):
        now = timezone.now()
        admin = self.user("admin@skyleon.local", "Ayesha Rahman", Role.SUPER_ADMIN, pw, title="Operations Director")
        pm = self.user("pm@skyleon.local", "Tanvir Hasan", Role.PROJECT_MANAGER, pw, title="Project Manager")
        trainer = self.user("trainer@skyleon.local", "Nusrat Jahan", Role.TRAINER, pw, title="QA Lead & Trainer")
        names = ["Rahim Uddin", "Sadia Islam", "Karim Ahmed", "Farhana Akter", "Imran Hossain", "Mitu Begum", "Jahid Khan", "Shila Roy"]
        employees = [
            self.user(f"employee{i + 1}@skyleon.local", n, Role.EMPLOYEE, pw, title="Annotator", location="Remote", skills=["CVAT", "Video segmentation"])
            for i, n in enumerate(names)
        ]
        pending = [
            self.user("new.member1@skyleon.local", "Arif Chowdhury", Role.EMPLOYEE, pw, status=UserStatus.PENDING, location="Dhaka"),
            self.user("new.member2@skyleon.local", "Lina Sarker", Role.EMPLOYEE, pw, status=UserStatus.PENDING, location="Remote"),
        ]
        org, _ = Organization.objects.get_or_create(slug="northwind-robotics", defaults={"name": "Northwind Robotics", "contact_email": "ops@northwind.example"})
        self.user("client@northwind.example", "Daniel Moore", Role.CLIENT, pw, organization=org)

        if Project.objects.filter(code="ACT-01").exists():
            self.stdout.write("Demo projects already exist — accounts refreshed only.")
            return

        act = Project.objects.create(
            name="Egocentric Action Segmentation", slug="egocentric-action-segmentation", code="ACT-01", organization=org,
            client_name="Northwind Robotics", status=ProjectStatus.ACTIVE, color="#6563f2",
            annotation_type="Video action segmentation + action descriptions", platform="Client annotation server",
            summary="Segment first-person videos into atomic actions and write Hand + Action + Object descriptions.",
            description="Large-scale egocentric video project. Each clip is segmented at action transitions and every segment gets a structured description (e.g. *Right hand picks up a cup*).",
            start_date=(now - timedelta(days=40)).date(),
        )
        rtl = Project.objects.create(
            name="Retail Shelf Detection", slug="retail-shelf-detection", code="RTL-02", client_name="Confidential retail client",
            status=ProjectStatus.ACTIVE, color="#06b6d4", annotation_type="Bounding boxes + product classification", platform="CVAT",
            summary="Detect and classify products on store shelf images.", start_date=(now - timedelta(days=12)).date(),
        )
        team_a = Team.objects.create(project=act, name="Team A", lead=employees[0])
        team_b = Team.objects.create(project=act, name="Team B", lead=employees[3])
        add_member(act, pm, role=MemberRole.MANAGER, notify_user=False)
        add_member(act, trainer, role=MemberRole.TRAINER, notify_user=False)
        add_member(rtl, pm, role=MemberRole.MANAGER, notify_user=False)
        for i, e in enumerate(employees[:6]):
            add_member(act, e, role=MemberRole.REVIEWER if i in (0, 3) else MemberRole.ANNOTATOR, team=team_a if i < 3 else team_b, notify_user=False)
        for e in employees[5:]:
            add_member(rtl, e, notify_user=False)

        g1 = Guideline.objects.create(project=act, order=1, version="2.1", title="Action segmentation rules", content=(
            "## Segment boundaries\n\n- Start a new segment when the **hand begins** a new action.\n- End the segment when the action is "
            "**complete** (object released, door closed …).\n- Do not create segments shorter than **0.5 s**.\n\n## Hand visibility\n\n"
            "If the hand leaves the frame for more than 1 second, close the segment and start a new one when it re-enters.\n"))
        g2 = Guideline.objects.create(project=act, order=2, version="1.4", title="Action description format", content=(
            "Every segment needs one description using **Hand + Action + Object**.\n\n| Good | Bad |\n|---|---|\n"
            "| Right hand picks up a cup. | Picking cup |\n| Left hand opens the drawer. | hand opens |\n\n"
            "- Use present tense.\n- Use *left hand*, *right hand* or *both hands*.\n- Name the object specifically (cup, not item)."))
        Guideline.objects.create(project=rtl, order=1, title="Bounding box rules", content="- Boxes must be **tight** to visible product edges.\n- Label occluded products if >30% visible.\n- Use class `unknown_product` only after checking the catalogue.")

        cat = self.categories
        t_intro = Tutorial.objects.create(title="Welcome to Skyleon — how we work", category=cat["Getting started"], cadence=Cadence.ONBOARDING,
                                          description="Company introduction, confidentiality rules and how the portal works.", video=self.video("welcome", 30), created_by=admin)
        t_seg = Tutorial.objects.create(title="Action segmentation fundamentals", project=act, category=cat["Annotation techniques"], cadence=Cadence.ONBOARDING,
                                        description="How to find action boundaries, handle transitions and avoid over-segmentation.", video=self.video("segmentation", 45, "0x4338ca"), created_by=trainer)
        t_desc = Tutorial.objects.create(title="Writing Hand + Action + Object descriptions", project=act, category=cat["Project guidelines"], cadence=Cadence.ONBOARDING,
                                         description="Structured descriptions with real examples from the project.", video=self.video("descriptions", 35, "0x0e7490"), created_by=trainer)
        t_daily = Tutorial.objects.create(title="Daily training: occluded hands", project=act, category=cat["Daily training"], cadence=Cadence.DAILY,
                                          description="Today's focus: how to segment when the hand is partially hidden.", video=self.video("daily-occlusion", 25, "0xbe185d"), created_by=trainer)
        t_cvat = Tutorial.objects.create(title="CVAT shortcuts for bounding boxes", project=rtl, category=cat["Tools & platforms"], cadence=Cadence.REFERENCE,
                                         description="Speed up box drawing and attribute editing in CVAT.", video=self.video("cvat", 30, "0x15803d"), created_by=trainer, is_required=False)
        for t in (t_intro, t_seg, t_desc, t_daily, t_cvat):
            publish_tutorial(t)

        tf = lambda: [("True", True), ("False", False)]  # noqa: E731
        onboarding_test = self.test("ACT-01 training test", act, TestKind.ONBOARDING, [
            ("When should a new action segment start?", QuestionType.SINGLE_CHOICE,
             [("When the hand begins a new action", True), ("Every 2 seconds", False), ("When the camera moves", False)], "Segments follow the hand's actions, not time or camera motion."),
            ("Which description follows the project format?", QuestionType.SINGLE_CHOICE,
             [("Right hand picks up a cup.", True), ("Picking cup", False), ("cup picked", False)], "Hand + Action + Object, present tense."),
            ("Segments shorter than 0.5 seconds are allowed.", QuestionType.TRUE_FALSE, [("True", False), ("False", True)], "Minimum segment length is 0.5 s."),
            ("Which of these are valid hand labels? (select all)", QuestionType.MULTI_SELECT,
             [("Left hand", True), ("Right hand", True), ("Both hands", True), ("Some hand", False)], ""),
        ], passing=75, attempts=3, author=trainer)
        publish_test(onboarding_test, assign=False)

        steps = [
            (OnboardingStepType.WELCOME, "Welcome & project introduction", "Meet the project and its goals.", "Welcome to **ACT-01**! You'll segment egocentric videos into atomic actions and write a description for each segment.", {}),
            (OnboardingStepType.GUIDELINE_VIDEO, "Project guidelines video", "Watch the company introduction.", "", {"tutorial": t_intro}),
            (OnboardingStepType.TUTORIAL, "Annotation tutorial", "Learn action segmentation.", "", {"tutorial": t_seg}),
            (OnboardingStepType.EXAMPLES, "Examples of correct work", "Study accepted segments.", "- *Right hand picks up a cup.* — starts when fingers close on the cup.\n- *Left hand opens the drawer.* — ends when the drawer stops moving.", {"guideline": g2}),
            (OnboardingStepType.COMMON_MISTAKES, "Common mistakes", "Avoid the top rejection reasons.", "1. Segment starts too late.\n2. Wrong hand.\n3. Generic object names (\"item\").\n4. Missing segments when the hand re-enters the frame.", {}),
            (OnboardingStepType.QA_GUIDELINES, "QA / review guidelines", "How reviewers score your work.", "Reviewers check boundary accuracy (±5 frames), hand/action/object match and guideline compliance.", {"guideline": g1}),
            (OnboardingStepType.TEST, "Training test", "Pass with 75% or more.", "", {"test": onboarding_test}),
            (OnboardingStepType.QUALIFICATION, "Final qualification", "Your manager reviews a sample batch.", "After you pass the test, complete a 20-clip sample batch. Your project manager will qualify you for production.", {}),
        ]
        for i, (stype, title, desc, content, rel) in enumerate(steps, start=1):
            OnboardingStep.objects.create(project=act, order=i, step_type=stype, title=title, description=desc, content=content, **rel)

        fb_test = self.test("Feedback #001 check", act, TestKind.FEEDBACK, [
            ("The hand leaves the frame for 2 seconds. What do you do?", QuestionType.SINGLE_CHOICE,
             [("Close the segment and start a new one when it re-enters", True), ("Keep one long segment", False), ("Delete the clip", False)], "See guideline: Hand visibility."),
            ("A partially visible hand (fingers only) still counts as visible.", QuestionType.TRUE_FALSE, tf(), "If you can identify the action, the hand is visible."),
        ], passing=100, attempts=2, author=trainer)
        fb1 = Feedback.objects.create(topic="Hand visibility", project=act, video=self.video("feedback-hand-visibility", 30, "0xb45309"), test=fb_test,
                                      summary="Several segments kept running while the hand was out of frame.", severity="important", created_by=trainer,
                                      explanation="When the hand **leaves the frame for more than 1 second**, close the current segment. Start a new segment when the hand re-enters and resumes an action.\n\n**Correct:** two segments around the gap.\n**Incorrect:** one long segment covering the gap.")
        publish_feedback(fb1)
        fb2 = Feedback.objects.create(topic="Object naming", project=act, team=team_b, created_by=trainer, cadence="weekly",
                                      summary="Use specific object names.", explanation="Write *cup*, *bottle*, *drawer* — never *item* or *thing*.")
        publish_feedback(fb2)

        # Realistic activity
        for i, e in enumerate(employees[:6]):
            for t in (t_intro, t_seg):
                p = TutorialProgress.objects.get(tutorial=t, user=e)
                if i < 4 or t == t_intro:
                    d = t.video.duration_sec or 30
                    p.watched_ranges, p.watched_seconds, p.percent = [[0, d]], d, 100
                    p.status, p.completed_at, p.first_viewed_at, p.last_viewed_at = "completed", now - timedelta(days=5 - i % 3), now - timedelta(days=6), now - timedelta(days=5)
                    p.save()
            if i < 4:
                a = start_attempt(e, onboarding_test)
                qs = {str(q.pk): [o.pk for o in q.options.all() if o.is_correct or (i == 3 and q.order == 0 and o.order == 1)] for q in onboarding_test.questions.all()}
                if i == 3:
                    qs[str(onboarding_test.questions.first().pk)] = [onboarding_test.questions.first().options.get(order=1).pk]
                submit_attempt(a, qs)
            rec = fb1.recipients.filter(user=e).first()
            if rec and i < 3:
                mark_opened(rec, has_video=True)
                rec.watched_at, rec.percent = now - timedelta(hours=10 - i), 100
                rec.save()
                a = start_attempt(e, fb_test)
                answers = {str(q.pk): [o.pk for o in q.options.all() if o.is_correct] for q in fb_test.questions.all()}
                if i == 2:
                    answers = {str(q.pk): [o.pk for o in q.options.all() if not o.is_correct][:1] for q in fb_test.questions.all()}
                submit_attempt(a, answers)
        from apps.projects.models import ProjectMember
        ProjectMember.objects.filter(project=act, user__in=employees[:2]).update(qualified_at=now - timedelta(days=2), qualified_by=pm)

        from apps.practice.models import PracticeTask

        PracticeTask.objects.create(
            title="Kitchen clip 001 — pick & place", project=act, video=t_seg.video, range_start=3, range_end=40,
            tolerance_sec=0.5, passing_score=75, status="published", published_at=now, created_by=trainer,
            instructions="Segment every hand action between **00:03** and **00:40**. Start a clip when the hand begins an action and end it when the action is complete.",
            reference_clips=[[4.0, 7.5], [8.0, 12.0], [12.5, 18.0], [19.0, 24.5], [25.0, 31.0], [32.0, 39.5]],
        )
        PracticeTask.objects.create(
            title="Kitchen clip 002 — open & close", project=act, video=t_desc.video, range_start=2, range_end=33,
            tolerance_sec=0.5, passing_score=75, status="published", published_at=now, created_by=trainer, order=1,
            instructions="Clip each open / close action. Remember: the clip ends when the door or drawer stops moving.",
            reference_clips=[[3.0, 6.0], [7.0, 11.5], [12.0, 17.0], [18.5, 24.0], [25.0, 32.0]],
        )

        Announcement.objects.create(title="New QA scoring starts Monday", project=act, priority="important", pinned=True, created_by=pm,
                                    body="From **Monday** reviewers will score boundary accuracy at ±5 frames. Please re-read the *Action segmentation rules* guideline.")
        Announcement.objects.create(title="Welcome to the new training portal", created_by=admin,
                                    body="All training videos, feedback and tests now live in this portal. Your progress is tracked automatically.")
        m = Meeting.objects.create(title="Weekly ACT-01 calibration call", project=act, created_by=pm, starts_at=now + timedelta(days=2, hours=3),
                                   duration_min=45, meeting_url="https://meet.google.com/abc-defg-hij", agenda="Review common mistakes from feedback #001 and #002.")
        MeetingInvite.objects.bulk_create([MeetingInvite(meeting=m, user=e) for e in employees[:6]])

        QuoteRequest.objects.create(name="Emily Carter", company="Vision Labs", email="emily@visionlabs.example", project_type="Video annotation",
                                    annotation_types=["Action segmentation", "Object tracking"], dataset_size="5,000 videos (~800 hours)", timeline="3 months",
                                    platform="Client-provided platform", requirements="Egocentric kitchen videos; need action segments with structured descriptions.")
        QuoteRequest.objects.create(name="Lukas Weber", company="Autonomo GmbH", email="lukas@autonomo.example", project_type="Image annotation",
                                    annotation_types=["Bounding boxes", "Semantic segmentation"], dataset_size="120k images", timeline="6 weeks", platform="CVAT", status="contacted")
        ContactMessage.objects.create(name="Priya Nair", email="priya@agrisense.example", company="AgriSense", subject="Crop annotation pilot",
                                      message="We'd like to discuss a pilot for fruit detection and counting.")
        JobApplication.objects.create(full_name="Rafi Islam", email="rafi.applicant@example.com", phone="+8801700000000", location="Chattogram",
                                      experience="1–2 years", annotation_experience="Bounding boxes and polygons in CVAT for a retail project.",
                                      preferred_work_type="Remote · full-time", availability="Immediately", skills=["CVAT", "Polygon", "Bounding boxes"])
        JobApplication.objects.create(full_name="Mou Akter", email="mou.applicant@example.com", phone="+8801800000000", location="Remote",
                                      experience="No experience", preferred_work_type="Remote · part-time", availability="Evenings", skills=["Excel"])

        self.stdout.write(self.style.SUCCESS("Demo data created."))
        self.stdout.write(f"  Super admin:     admin@skyleon.local / {pw}")
        self.stdout.write(f"  Project manager: pm@skyleon.local / {pw}")
        self.stdout.write(f"  Trainer / QA:    trainer@skyleon.local / {pw}")
        self.stdout.write(f"  Employees:       employee1..8@skyleon.local / {pw}  (pending: new.member1/2@skyleon.local)")
        self.stdout.write(f"  Client:          client@northwind.example / {pw}")
