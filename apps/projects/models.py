from django.conf import settings
from django.db import models
from django.urls import reverse


class ProjectStatus(models.TextChoices):
    PLANNING = "planning", "Planning"
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    COMPLETED = "completed", "Completed"
    ARCHIVED = "archived", "Archived"


class MemberRole(models.TextChoices):
    ANNOTATOR = "annotator", "Annotator"
    REVIEWER = "reviewer", "Reviewer"
    QA = "qa", "QA"
    TEAM_LEAD = "team_lead", "Team lead"
    MANAGER = "manager", "Project manager"
    TRAINER = "trainer", "Trainer"


class Project(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text="Short code, e.g. ACT-01")
    summary = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True, help_text="Markdown supported")
    client_name = models.CharField(max_length=200, blank=True, help_text="Use a code name for confidential clients")
    organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="projects"
    )
    status = models.CharField(max_length=20, choices=ProjectStatus.choices, default=ProjectStatus.ACTIVE, db_index=True)
    annotation_type = models.CharField(max_length=200, blank=True)
    platform = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=9, default="#6366f1")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("portal:project_detail", args=[self.slug])


class Team(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=120)
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="led_teams")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["project", "name"], name="uniq_team_name_per_project")]

    def __str__(self):
        return f"{self.project.code} · {self.name}"


class ProjectMember(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=MemberRole.choices, default=MemberRole.ANNOTATOR)
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    assigned_at = models.DateTimeField(auto_now_add=True)
    qualified_at = models.DateTimeField(null=True, blank=True, help_text="Final qualification (onboarding step 8)")
    qualified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [models.UniqueConstraint(fields=["project", "user"], name="uniq_project_member")]

    def __str__(self):
        return f"{self.user} @ {self.project}"


class Guideline(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="guidelines")
    title = models.CharField(max_length=200)
    content = models.TextField(help_text="Markdown supported")
    version = models.CharField(max_length=20, default="1.0")
    order = models.PositiveIntegerField(default=0)
    document = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title"]

    def __str__(self):
        return self.title


class GuidelineAck(models.Model):
    guideline = models.ForeignKey(Guideline, on_delete=models.CASCADE, related_name="acks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="guideline_acks")
    version = models.CharField(max_length=20)
    acknowledged_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["guideline", "user"], name="uniq_guideline_ack")]
