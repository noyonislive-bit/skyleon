from django.conf import settings
from django.db import models


class LeadStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    QUALIFIED = "qualified", "Qualified"
    PROPOSAL = "proposal", "Proposal sent"
    WON = "won", "Won"
    LOST = "lost", "Lost"
    ARCHIVED = "archived", "Archived"


class QuoteRequest(models.Model):
    name = models.CharField(max_length=150)
    company = models.CharField(max_length=200, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    project_type = models.CharField(max_length=100)
    annotation_types = models.JSONField(default=list, blank=True)
    dataset_size = models.CharField(max_length=100, blank=True)
    timeline = models.CharField(max_length=100, blank=True)
    platform = models.CharField(max_length=100, blank=True)
    requirements = models.TextField(blank=True)
    attachment = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW, db_index=True)
    notes = models.TextField(blank=True)
    source = models.CharField(max_length=200, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.company or self.email})"


class ContactMessage(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField()
    company = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name}: {self.subject or self.message[:40]}"


class ApplicationStatus(models.TextChoices):
    NEW = "new", "New"
    REVIEWING = "reviewing", "Reviewing"
    SHORTLISTED = "shortlisted", "Shortlisted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class JobApplication(models.Model):
    full_name = models.CharField(max_length=150)
    email = models.EmailField(db_index=True)
    phone = models.CharField(max_length=40)
    location = models.CharField(max_length=120)
    experience = models.CharField(max_length=60, blank=True)
    annotation_experience = models.TextField(blank=True)
    preferred_work_type = models.CharField(max_length=60, blank=True)
    availability = models.CharField(max_length=100, blank=True)
    skills = models.JSONField(default=list, blank=True)
    portfolio_url = models.URLField(max_length=500, blank=True)
    cv = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sample = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.NEW, db_index=True)
    notes = models.TextField(blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="application",
        help_text="Employee account created from this application",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.full_name
