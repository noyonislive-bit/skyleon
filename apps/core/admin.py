"""
Low-level Django admin (/django-admin/) for super admins — a safety net for
editing raw records. Day-to-day management happens in the custom admin panel (/admin/).
All registrations live here so feature apps stay free of admin boilerplate.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import Organization, User
from apps.assessments.models import Question, QuestionOption, Test, TestAssignment, TestAttempt
from apps.comms.models import Announcement, EmailMessage, Meeting, Notification
from apps.feedback.models import Feedback, FeedbackRecipient
from apps.projects.models import Guideline, Project, ProjectMember, Team
from apps.storage.models import MediaAsset
from apps.training.models import OnboardingStep, Tutorial, TutorialCategory, TutorialProgress
from apps.practice.models import PracticeAttempt, PracticeTask
from apps.website.models import ContactMessage, JobApplication, QuoteRequest

from .models import AuditLog, SiteSetting


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["name"]
    list_display = ["name", "email", "employee_id", "role", "status", "last_login"]
    list_filter = ["role", "status"]
    search_fields = ["name", "email", "employee_id"]
    readonly_fields = ["last_login", "date_joined", "approved_at"]
    fieldsets = (
        (None, {"fields": ("email", "password", "employee_id")}),
        ("Profile", {"fields": ("name", "phone", "location", "title", "bio", "skills", "organization")}),
        ("Access", {"fields": ("role", "status", "is_staff", "is_superuser")}),
        ("Dates", {"fields": ("last_login", "date_joined", "approved_at")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "name", "role", "status", "password1", "password2")}),)
    filter_horizontal = ()


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["prompt", "test", "qtype", "points"]
    list_filter = ["qtype"]
    inlines = [QuestionOptionInline]


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "project", "status", "passing_score", "attempt_limit"]
    list_filter = ["kind", "status", "project"]
    search_fields = ["title"]


@admin.register(TestAttempt)
class TestAttemptAdmin(admin.ModelAdmin):
    list_display = ["test", "user", "attempt_number", "score", "passed", "submitted_at"]
    list_filter = ["passed", "test"]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["display_number", "topic", "project", "team", "status", "published_at"]
    list_filter = ["status", "project", "severity"]
    search_fields = ["topic"]


@admin.register(Tutorial)
class TutorialAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "category", "is_required", "status", "published_at"]
    list_filter = ["status", "project", "category", "is_required"]
    search_fields = ["title"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "status", "client_name", "start_date"]
    list_filter = ["status"]
    search_fields = ["name", "code"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = ["to", "subject", "template", "status", "attempts", "created_at", "sent_at"]
    list_filter = ["status", "template"]
    search_fields = ["to", "subject"]


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ["original_name", "kind", "provider", "status", "size_bytes", "created_at"]
    list_filter = ["kind", "provider", "status"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "action", "entity_type", "entity_id", "ip_address"]
    list_filter = ["action"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]


for model in (
    Organization, SiteSetting, Team, ProjectMember, Guideline, TutorialCategory, TutorialProgress, OnboardingStep,
    FeedbackRecipient, TestAssignment, Announcement, Meeting, Notification, QuoteRequest, ContactMessage, JobApplication,
    PracticeTask, PracticeAttempt,
):
    admin.site.register(model)
