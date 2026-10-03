from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.choices import ContentStatus, ProgressStatus


class TutorialCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "tutorial categories"

    def __str__(self):
        return self.name


class Cadence(models.TextChoices):
    ONBOARDING = "onboarding", "Onboarding"
    DAILY = "daily", "Daily training"
    WEEKLY = "weekly", "Weekly training"
    REFERENCE = "reference", "Reference"


class Tutorial(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, help_text="Markdown supported")
    category = models.ForeignKey(TutorialCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="tutorials")
    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="tutorials",
        help_text="Leave empty for company-wide training",
    )
    video = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_required = models.BooleanField(default=True)
    cadence = models.CharField(max_length=20, choices=Cadence.choices, default=Cadence.REFERENCE)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.DRAFT, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("portal:tutorial_detail", args=[self.pk])

    @property
    def is_published(self):
        return self.status == ContentStatus.PUBLISHED


class TutorialProgress(models.Model):
    """
    One row per employee per tutorial. Created when the tutorial is assigned
    (publish / project join / manual assignment) or when an employee opens an
    optional tutorial. Updated by the tracked video player heartbeats.
    """

    tutorial = models.ForeignKey(Tutorial, on_delete=models.CASCADE, related_name="progress")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tutorial_progress")
    assigned = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ProgressStatus.choices, default=ProgressStatus.NOT_STARTED, db_index=True)
    watched_ranges = models.JSONField(default=list, blank=True)  # [[start, end], …] seconds actually played
    watched_seconds = models.FloatField(default=0)
    percent = models.FloatField(default=0)
    last_position_sec = models.FloatField(default=0)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tutorial", "user"], name="uniq_tutorial_progress")]
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"{self.user} · {self.tutorial} · {self.percent:.0f}%"

    @property
    def is_completed(self):
        return self.status == ProgressStatus.COMPLETED


class OnboardingStepType(models.TextChoices):
    WELCOME = "welcome", "Welcome / project introduction"
    GUIDELINE_VIDEO = "guideline_video", "Project guidelines video"
    TUTORIAL = "tutorial", "Annotation tutorial"
    EXAMPLES = "examples", "Examples of correct work"
    COMMON_MISTAKES = "common_mistakes", "Common mistakes"
    QA_GUIDELINES = "qa_guidelines", "QA / review guidelines"
    TEST = "test", "Training test"
    QUALIFICATION = "qualification", "Final qualification"
    CUSTOM = "custom", "Custom step"


class OnboardingStep(models.Model):
    """
    Completion rules (evaluated live, see training.services.onboarding):
      * tutorial set      → done when the tutorial is completed (tracked playback)
      * test set          → done when the test is passed
      * QUALIFICATION     → done when a manager qualifies the member on the project
      * otherwise         → done when the employee confirms the step
    """

    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="onboarding_steps",
        help_text="Leave empty for company-wide onboarding",
    )
    order = models.PositiveIntegerField(default=1)
    step_type = models.CharField(max_length=30, choices=OnboardingStepType.choices, default=OnboardingStepType.CUSTOM)
    title = models.CharField(max_length=200)
    description = models.CharField(max_length=300, blank=True)
    content = models.TextField(blank=True, help_text="Markdown supported")
    tutorial = models.ForeignKey(Tutorial, null=True, blank=True, on_delete=models.SET_NULL, related_name="onboarding_steps")
    test = models.ForeignKey("assessments.Test", null=True, blank=True, on_delete=models.SET_NULL, related_name="onboarding_steps")
    guideline = models.ForeignKey("projects.Guideline", null=True, blank=True, on_delete=models.SET_NULL, related_name="onboarding_steps")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project_id", "order"]

    def __str__(self):
        return f"{self.order}. {self.title}"


class OnboardingCompletion(models.Model):
    step = models.ForeignKey(OnboardingStep, on_delete=models.CASCADE, related_name="completions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="onboarding_completions")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["step", "user"], name="uniq_onboarding_completion")]
