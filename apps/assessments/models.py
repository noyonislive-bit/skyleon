from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.choices import ContentStatus


class TestKind(models.TextChoices):
    TRAINING = "training", "Training test"
    FEEDBACK = "feedback", "Feedback test"
    ONBOARDING = "onboarding", "Onboarding test"
    QUALIFICATION = "qualification", "Qualification test"


class QuestionType(models.TextChoices):
    SINGLE_CHOICE = "single", "Multiple choice (one answer)"
    MULTI_SELECT = "multi", "Multiple choice (several answers)"
    TRUE_FALSE = "true_false", "True / False"


class Test(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=TestKind.choices, default=TestKind.TRAINING)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="tests")
    passing_score = models.PositiveSmallIntegerField(default=80, help_text="Percent required to pass")
    attempt_limit = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Empty = unlimited attempts")
    time_limit_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Empty = no time limit")
    shuffle_questions = models.BooleanField(default=False)
    reveal_answers = models.BooleanField(default=True, help_text="Show correct answers after submission")
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.DRAFT, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("portal:test_detail", args=[self.pk])

    @property
    def is_published(self):
        return self.status == ContentStatus.PUBLISHED


class Question(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField(default=0)
    qtype = models.CharField("Type", max_length=20, choices=QuestionType.choices, default=QuestionType.SINGLE_CHOICE)
    prompt = models.TextField()
    explanation = models.TextField(blank=True, help_text="Shown after submission when answers are revealed")
    media = models.ForeignKey(
        "storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Image or video shown with the question",
    )
    points = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.prompt[:60]


class QuestionOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    order = models.PositiveIntegerField(default=0)
    text = models.CharField(max_length=500, blank=True)
    media = models.ForeignKey(
        "storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Image option, e.g. 'select the correct segmentation'",
    )
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text or f"Option {self.order}"


class TestAssignment(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="test_assignments")
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    due_at = models.DateTimeField(null=True, blank=True)
    extra_attempts = models.PositiveSmallIntegerField(
        default=0, help_text="Attempts granted to this person on top of the test's attempt limit"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["test", "user"], name="uniq_test_assignment")]


class TestAttempt(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="attempts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="test_attempts")
    attempt_number = models.PositiveSmallIntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    score = models.FloatField(null=True, blank=True)  # percent
    points_earned = models.PositiveIntegerField(null=True, blank=True)
    points_total = models.PositiveIntegerField(null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)
    # Question order shown to the employee + graded answers:
    # {"order": [qid…], "answers": [{"question": qid, "selected": [oid…], "correct": bool, "points": n}]}
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [models.UniqueConstraint(fields=["test", "user", "attempt_number"], name="uniq_test_attempt")]
        indexes = [models.Index(fields=["user", "submitted_at"]), models.Index(fields=["test", "submitted_at"])]

    def __str__(self):
        return f"{self.user} · {self.test} · #{self.attempt_number}"

    @property
    def is_submitted(self):
        return self.submitted_at is not None
