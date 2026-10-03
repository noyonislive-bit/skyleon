from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.choices import ContentStatus


class Severity(models.TextChoices):
    NORMAL = "normal", "Normal"
    IMPORTANT = "important", "Important"
    CRITICAL = "critical", "Critical"


class FeedbackCadence(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    ADHOC = "adhoc", "Ad-hoc"


class Feedback(models.Model):
    """A QA feedback item (e.g. "#001 · Hand visibility") with optional video and test."""

    number = models.PositiveIntegerField(unique=True, editable=False, help_text="Displayed as #001")
    topic = models.CharField(max_length=200)
    summary = models.CharField(max_length=300, blank=True)
    explanation = models.TextField(help_text="Markdown: the correct way to handle this type of task")
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="feedback")
    team = models.ForeignKey(
        "projects.Team", null=True, blank=True, on_delete=models.SET_NULL, related_name="feedback",
        help_text="Leave empty to send to the whole project",
    )
    video = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    test = models.OneToOneField(
        "assessments.Test", null=True, blank=True, on_delete=models.SET_NULL, related_name="feedback",
        help_text="Short test employees take after watching",
    )
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.NORMAL)
    cadence = models.CharField(max_length=20, choices=FeedbackCadence.choices, default=FeedbackCadence.DAILY)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.DRAFT, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    due_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-number"]
        verbose_name_plural = "feedback"

    def __str__(self):
        return f"{self.display_number} · {self.topic}"

    def save(self, *args, **kwargs):
        if not self.number:
            from apps.core.models import Counter

            self.number = Counter.next("feedback_number")
        super().save(*args, **kwargs)

    @property
    def display_number(self):
        return f"#{self.number:03d}"

    @property
    def is_published(self):
        return self.status == ContentStatus.PUBLISHED

    def get_absolute_url(self):
        return reverse("portal:feedback_detail", args=[self.number])


class FeedbackRecipient(models.Model):
    """Who received a feedback item and what they did with it."""

    feedback = models.ForeignKey(Feedback, on_delete=models.CASCADE, related_name="recipients")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedback_received")
    assigned_at = models.DateTimeField(auto_now_add=True)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    watched_ranges = models.JSONField(default=list, blank=True)
    watched_seconds = models.FloatField(default=0)
    percent = models.FloatField(default=0)
    last_position_sec = models.FloatField(default=0)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    watched_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Video watched (or opened, if no video)")
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["feedback", "user"], name="uniq_feedback_recipient")]
        indexes = [models.Index(fields=["user", "watched_at"])]

    @property
    def is_seen(self):
        return self.first_viewed_at is not None

    @property
    def is_watched(self):
        return self.watched_at is not None
