from django.conf import settings
from django.db import models


class Announcement(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField(help_text="Markdown supported")
    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="announcements",
        help_text="Leave empty to send to everyone",
    )
    priority = models.CharField(max_length=20, choices=[("normal", "Normal"), ("important", "Important")], default="normal")
    pinned = models.BooleanField(default=False)
    published_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-pinned", "-published_at"]

    def __str__(self):
        return self.title


class AnnouncementRead(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcement_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["announcement", "user"], name="uniq_announcement_read")]


class Meeting(models.Model):
    title = models.CharField(max_length=200)
    agenda = models.TextField(blank=True)
    meeting_url = models.URLField(max_length=500, blank=True, help_text="Google Meet / Zoom / Teams link")
    starts_at = models.DateTimeField(db_index=True)
    duration_min = models.PositiveSmallIntegerField(default=30)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="meetings")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self):
        return self.title


class MeetingInvite(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="invites")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="meeting_invites")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["meeting", "user"], name="uniq_meeting_invite")]


class NotificationType(models.TextChoices):
    TRAINING = "training", "Training"
    FEEDBACK = "feedback", "Feedback"
    TEST = "test", "Test"
    ANNOUNCEMENT = "announcement", "Announcement"
    MEETING = "meeting", "Meeting"
    ACCOUNT = "account", "Account"
    PROJECT = "project", "Project"
    SYSTEM = "system", "System"


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    ntype = models.CharField("Type", max_length=20, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    link = models.CharField(max_length=300, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]


class EmailStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class EmailMessage(models.Model):
    """Outbox. Every email is stored first, then delivered (immediately or by the cron job)."""

    to = models.EmailField()
    subject = models.CharField(max_length=300)
    html = models.TextField()
    text = models.TextField()
    template = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=EmailStatus.choices, default=EmailStatus.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.to}: {self.subject}"
