"""
Practice Lab — hands-on training in a replica of the production video-clipping tool.

A trainer uploads a real (or sample) video, marks the "hands present" range and
records a reference segmentation with the same tool. Employees clip the video
themselves; their clips are scored automatically against the reference.

Two kinds of task:
  • instant — the trainer's reference exists first; every submission is scored at once.
  • review (weekly review) — everyone clips a hard video and submits first (their work is kept);
    afterwards a reviewer clips the same video in the same tool and publishes that answer. Each
    employee then sees their own clips next to the reviewer's with the match %, and corrects their
    own work until it matches (correction attempts are scored, so the improvement is visible).
"""

from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.choices import ContentStatus


class TaskKind(models.TextChoices):
    INSTANT = "instant", "Instant score (trainer reference first)"
    REVIEW = "review", "Weekly review (employees first, reviewer's answer later)"


class PracticeTask(models.Model):
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=TaskKind.choices, default=TaskKind.INSTANT)
    due_at = models.DateTimeField(null=True, blank=True, help_text="Weekly review: submit by this time (later submissions are marked late)")
    answer_published_at = models.DateTimeField(null=True, blank=True, help_text="Weekly review: when the reviewer's answer was released")
    answer_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    instructions = models.TextField(blank=True, help_text="Markdown supported — shown before the employee starts")
    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="practice_tasks",
        help_text="Leave empty to make it available to every employee",
    )
    video = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    range_start = models.FloatField(default=0, help_text="Start of the 'hands present' range (seconds)")
    range_end = models.FloatField(null=True, blank=True, help_text="End of the 'hands present' range (seconds). Empty = end of video")
    reference_clips = models.JSONField(default=list, blank=True, help_text="Reference segmentation [[start, end], …]")
    tolerance_sec = models.FloatField(default=0.5, help_text="Allowed boundary difference when scoring (seconds)")
    passing_score = models.PositiveSmallIntegerField(default=80)
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.DRAFT, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("practice:workspace", args=[self.pk])

    @property
    def is_published(self):
        return self.status == ContentStatus.PUBLISHED

    @property
    def has_reference(self):
        return bool(self.reference_clips)

    @property
    def is_review(self):
        return self.kind == TaskKind.REVIEW

    @property
    def answer_published(self):
        return self.is_review and self.answer_published_at is not None

    @property
    def scores_now(self):
        """Submissions are scored at once — always for instant tasks, after the answer for review tasks."""
        return not self.is_review or self.answer_published_at is not None

    def effective_range(self, duration=None):
        duration = duration or (self.video.duration_sec if self.video_id and self.video else None)
        end = self.range_end if self.range_end is not None else duration
        return float(self.range_start or 0), float(end) if end else None


class AttemptStatus(models.TextChoices):
    DRAFT = "draft", "In progress"
    SUBMITTED = "submitted", "Submitted"


class AttemptPhase(models.TextChoices):
    FIRST = "first", "Own work"
    CORRECTION = "correction", "Correction after the answer"


class PracticeAttempt(models.Model):
    task = models.ForeignKey(PracticeTask, on_delete=models.CASCADE, related_name="attempts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="practice_attempts")
    status = models.CharField(max_length=20, choices=AttemptStatus.choices, default=AttemptStatus.DRAFT, db_index=True)
    phase = models.CharField(max_length=20, choices=AttemptPhase.choices, default=AttemptPhase.FIRST)
    clips = models.JSONField(default=list, blank=True)  # [[start, end], …]
    score = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)
    metrics = models.JSONField(default=dict, blank=True)  # coverage, boundary F1, IoU, issues …
    task_error = models.JSONField(default=dict, blank=True)  # {"reason": …, "comment": …, "at": …}
    time_spent_sec = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["task", "user", "status"])]

    def __str__(self):
        return f"{self.user} · {self.task} · {self.status}"

    def get_absolute_url(self):
        return reverse("practice:result", args=[self.pk])
