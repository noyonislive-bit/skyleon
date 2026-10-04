"""Forms used by the admin panel. Business rules stay in the services."""

import re
import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.forms import ProfileForm
from apps.accounts.models import Organization, Role, User
from apps.accounts.permissions import can_manage_content_for, has_permission, is_unscoped
from apps.assessments.models import Question, QuestionType, Test, TestKind
from apps.comms.models import Announcement, Meeting
from apps.core.choices import ContentStatus
from apps.core.forms import StyledFormMixin
from apps.feedback.models import Feedback
from apps.projects.models import Guideline, MemberRole, Project, Team
from apps.storage.models import MediaAsset, MediaKind, MediaStatus
from apps.training.models import OnboardingStep, OnboardingStepType, Tutorial, TutorialCategory
from apps.website.models import ApplicationStatus, ContactMessage, JobApplication, LeadStatus, QuoteRequest

from .helpers import assignable_employees, assignable_people, can_target_project, staff_projects
from .media import can_attach_asset

DATETIME_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def date_widget():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def datetime_widget():
    return forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


# ── Custom fields / widgets ─────────────────────────────────────────────────

class MediaAssetField(forms.Field):
    """
    Hidden input holding a MediaAsset UUID, filled by static/js/uploader.js.

    Only accepts files the user may attach: their own uploads, files already attached to
    content in their scope, or the field's current (saved) value. The form binds the user with
    `bind_media_fields(form, user)`; an unbound field accepts nothing but the current value.
    """

    widget = forms.HiddenInput
    NOT_FOUND = "The uploaded file was not found or is not ready yet — please upload it again."

    def __init__(self, *, kinds=(MediaKind.VIDEO,), **kwargs):
        self.kinds = tuple(kinds)
        self.user = None
        self.current = None  # pk of the saved asset — always allowed
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def prepare_value(self, value):
        if isinstance(value, MediaAsset):
            return str(value.pk)
        return value

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, MediaAsset):
            return value
        try:
            pk = uuid.UUID(str(value))
        except ValueError:
            raise ValidationError("Invalid file reference.")
        asset = MediaAsset.objects.filter(pk=pk, kind__in=self.kinds, status=MediaStatus.READY).first()
        if asset is None or not self.allowed(asset):
            raise ValidationError(self.NOT_FOUND)
        return asset

    def allowed(self, asset) -> bool:
        if self.current is not None and str(asset.pk) == str(self.current):
            return True
        return can_attach_asset(self.user, asset)


def bind_media_fields(form, user):
    """Tell every MediaAssetField of `form` who is editing and which asset is already saved."""
    for name, field in form.fields.items():
        if isinstance(field, MediaAssetField):
            field.user = user
            current = form.initial.get(name)
            if current is None and getattr(form, "instance", None) is not None and form.instance.pk:
                current = getattr(form.instance, f"{name}_id", None)
            field.current = current.pk if isinstance(current, MediaAsset) else current


class ParentSelect(forms.Select):
    """<option data-parent="…"> so backoffice.js can filter e.g. teams by the selected project."""

    def __init__(self, *args, parent_attr="project_id", **kwargs):
        self.parent_attr = parent_attr
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-parent"] = getattr(instance, self.parent_attr) or ""
        return option


def person_label(obj):
    ident = obj.employee_id or obj.email
    role = "" if obj.role == Role.EMPLOYEE else f" · {obj.get_role_display()}"
    return f"{obj.name} · {ident}{role}"


class PersonLabelMixin:
    def label_from_instance(self, obj):
        return person_label(obj)


class PersonChoiceField(PersonLabelMixin, forms.ModelChoiceField):
    pass


class PeopleChoiceField(PersonLabelMixin, forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple


def set_project_field(field, user, *, allow_global, global_label="Company-wide"):
    field.queryset = staff_projects(user).order_by("name")
    field.required = not allow_global
    field.empty_label = global_label if allow_global else "Select a project"


# ── People ──────────────────────────────────────────────────────────────────

class EmployeeCreateForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label="Full name", max_length=150)
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[], initial=Role.EMPLOYEE)
    title = forms.CharField(label="Job title", max_length=120, required=False)
    phone = forms.CharField(max_length=40, required=False)
    location = forms.CharField(label="City / country", max_length=120, required=False)
    project = forms.ModelChoiceField(queryset=Project.objects.none(), required=False, empty_label="No project yet",
                                     help_text="Optional — adds the account to a project and assigns its training.")
    send_invite = forms.BooleanField(label="Email a link to set the password", required=False, initial=True)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if has_permission(user, "staff.manage"):
            self.fields["role"].choices = [c for c in Role.choices if c[0] != Role.CLIENT]
        else:
            self.fields["role"].choices = [(Role.EMPLOYEE, Role.EMPLOYEE.label)]
            self.fields["role"].widget = forms.HiddenInput()
        self.fields["project"].queryset = staff_projects(user).order_by("name")
        if not has_permission(user, "projects.manage"):
            del self.fields["project"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role != Role.EMPLOYEE and not has_permission(self.user, "staff.manage"):
            raise ValidationError("You can only create employee accounts.")
        return role


class EmployeeEditForm(ProfileForm):
    email = forms.EmailField()

    class Meta(ProfileForm.Meta):
        fields = ["name", "email", "phone", "location", "title", "bio"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        # The email is the login: changing it and then sending a password link would hand the
        # account to whoever owns the new address, so only super admins may change it.
        if not has_permission(user, "staff.manage"):
            self.fields["email"].disabled = True
            self.fields["email"].help_text = "Only a super admin can change the email address."

    def clean_email(self):
        if self.fields["email"].disabled:
            return self.instance.email
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Another account already uses this email.")
        return email


class RoleForm(StyledFormMixin, forms.Form):
    role = forms.ChoiceField(choices=Role.choices)


# ── Client organisations & client accounts ──────────────────────────────────

class OrganizationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "slug", "contact_email"]
        labels = {"name": "Organisation name", "contact_email": "Contact email"}
        help_texts = {
            "slug": "Short unique identifier. Leave empty to generate it from the name.",
            "contact_email": "Optional — the main contact at the client.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].widget.attrs.pop("required", None)

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean_slug(self):
        typed = slugify(self.cleaned_data.get("slug") or "")[:120]
        others = Organization.objects.exclude(pk=self.instance.pk)
        if typed:
            if others.filter(slug=typed).exists():
                raise ValidationError("Another organisation already uses this slug.")
            return typed
        base = slugify(self.cleaned_data.get("name") or "")[:110] or "organisation"
        slug, n = base, 2
        while others.filter(slug=slug).exists():
            slug, n = f"{base}-{n}", n + 1
        return slug


class ClientCreateForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label="Full name", max_length=150)
    email = forms.EmailField(help_text="They sign in with this email on the client login page.")
    title = forms.CharField(label="Job title", max_length=120, required=False)
    phone = forms.CharField(max_length=40, required=False)
    send_invite = forms.BooleanField(label="Email a link to set the password", required=False, initial=True)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email


class ClientEditForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["name", "email", "title", "phone", "organization"]
        labels = {"name": "Full name", "organization": "Organisation"}
        help_texts = {"organization": "The client sees the projects linked to this organisation."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].required = True
        self.fields["organization"].empty_label = "Select an organisation"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Another account already uses this email.")
        return email


class LinkProjectForm(StyledFormMixin, forms.Form):
    project = forms.ModelChoiceField(queryset=Project.objects.none(), empty_label="Select a project")

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["project"]
        field.queryset = Project.objects.exclude(organization=organization).select_related("organization").order_by("name")
        field.label_from_instance = lambda p: f"{p.code} · {p.name}" + (f" (now: {p.organization.name})" if p.organization_id else "")


class MembershipForm(StyledFormMixin, forms.Form):
    """Assign one person to a project (employee detail page)."""

    project = forms.ModelChoiceField(queryset=Project.objects.none(), empty_label="Select a project")
    role = forms.ChoiceField(choices=MemberRole.choices, initial=MemberRole.ANNOTATOR)
    team = forms.ModelChoiceField(queryset=Team.objects.none(), required=False, empty_label="No team",
                                  widget=ParentSelect(attrs={"data-depends-on": "project"}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        projects = staff_projects(user).order_by("name")
        self.fields["project"].queryset = projects
        self.fields["team"].queryset = Team.objects.filter(project__in=projects).select_related("project").order_by("name")
        self.fields["team"].label_from_instance = lambda t: t.name

    def clean(self):
        data = super().clean()
        project, team = data.get("project"), data.get("team")
        if team and project and team.project_id != project.pk:
            self.add_error("team", "This team belongs to another project.")
        return data


class AddMembersForm(StyledFormMixin, forms.Form):
    """Add several people to one project (project members tab)."""

    users = PeopleChoiceField(queryset=User.objects.none(), label="People")
    role = forms.ChoiceField(choices=MemberRole.choices, initial=MemberRole.ANNOTATOR)
    team = forms.ModelChoiceField(queryset=Team.objects.none(), required=False, empty_label="No team")

    def __init__(self, *args, user, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["users"].queryset = (
            assignable_people(user).exclude(memberships__project=project).order_by("name")
        )
        self.fields["team"].queryset = project.teams.all()
        self.fields["team"].label_from_instance = lambda t: t.name


class MemberUpdateForm(StyledFormMixin, forms.Form):
    role = forms.ChoiceField(choices=MemberRole.choices)
    team = forms.ModelChoiceField(queryset=Team.objects.none(), required=False, empty_label="No team")

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].queryset = project.teams.all()
        self.fields["team"].label_from_instance = lambda t: t.name


class AssignTutorialForm(StyledFormMixin, forms.Form):
    tutorial = forms.ModelChoiceField(queryset=Tutorial.objects.none(), empty_label="Select a published tutorial")
    due_date = forms.DateField(required=False, widget=date_widget(), label="Due date (optional)")

    def __init__(self, *args, tutorials, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tutorial"].queryset = tutorials
        self.fields["tutorial"].label_from_instance = lambda t: f"{t.title} · {t.project.code if t.project_id else 'Company-wide'}"


class AssignFeedbackForm(StyledFormMixin, forms.Form):
    feedback = forms.ModelChoiceField(queryset=Feedback.objects.none(), empty_label="Select published feedback")

    def __init__(self, *args, feedback, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["feedback"].queryset = feedback


class AssignTestForm(StyledFormMixin, forms.Form):
    test = forms.ModelChoiceField(queryset=Test.objects.none(), empty_label="Select a published test")
    due_date = forms.DateField(required=False, widget=date_widget(), label="Due date (optional)")

    def __init__(self, *args, tests, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["test"].queryset = tests
        self.fields["test"].label_from_instance = lambda t: f"{t.title} · {t.project.code if t.project_id else 'Company-wide'}"


class AssignPeopleForm(StyledFormMixin, forms.Form):
    """Pick employees (+ optional due date) for a tutorial / test."""

    users = PeopleChoiceField(queryset=User.objects.none(), label="Employees")
    due_date = forms.DateField(required=False, widget=date_widget(), label="Due date (optional)")

    def __init__(self, *args, user, queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["users"].queryset = (queryset if queryset is not None else assignable_employees(user)).order_by("name")


class ApplicationUpdateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = ["status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Internal notes — not visible to the applicant"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [c for c in ApplicationStatus.choices if c[0] != ApplicationStatus.APPROVED]
        if self.instance.status == ApplicationStatus.APPROVED:
            self.fields["status"].choices = ApplicationStatus.choices


class QuoteUpdateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = QuoteRequest
        fields = ["status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 5, "placeholder": "Internal notes — call summaries, pricing, next steps …"})}


class MessageUpdateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ["status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 5, "placeholder": "Internal notes — replies sent, follow-ups …"})}


# ── Projects ────────────────────────────────────────────────────────────────

class ProjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "code", "slug", "status", "summary", "description", "client_name", "organization",
                  "annotation_type", "platform", "color", "start_date", "end_date"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "color": forms.TextInput(attrs={"type": "color", "class": "h-11 p-1"}),
            "start_date": date_widget(),
            "end_date": date_widget(),
        }
        help_texts = {
            "slug": "Used in portal URLs. Leave empty to generate from the name.",
            "status": "Archived projects are hidden from employees; a super admin can then delete them permanently.",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].widget.attrs.pop("required", None)
        self.fields["organization"].empty_label = "No client organisation"
        # The client organisation decides which client accounts see the project (client portal).
        if not has_permission(user, "staff.manage"):
            self.fields["organization"].disabled = True
            self.fields["organization"].help_text = "Only a super admin can change the client organisation."

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()

    def clean_color(self):
        color = (self.cleaned_data.get("color") or "").strip()
        if not COLOR_RE.match(color):
            raise ValidationError("Use a hex colour like #088650.")
        return color.lower()

    def clean_slug(self):
        slug = slugify(self.cleaned_data.get("slug") or self.cleaned_data.get("name") or "")[:120]
        if not slug:
            raise ValidationError("Enter a slug.")
        if Project.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Another project already uses this slug.")
        return slug

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", "End date is before the start date.")
        return data


class TeamForm(StyledFormMixin, forms.ModelForm):
    lead = PersonChoiceField(queryset=User.objects.none(), required=False, empty_label="No lead")

    class Meta:
        model = Team
        fields = ["name", "lead"]

    def __init__(self, *args, project, lead_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["lead"].queryset = User.objects.filter(memberships__project=project).order_by("name")
        if lead_choices is not None:  # pre-rendered once per page instead of one query per team row
            self.fields["lead"].widget.choices = lead_choices

    @staticmethod
    def lead_choices(project):
        people = User.objects.filter(memberships__project=project).order_by("name")
        return [("", "No lead")] + [(u.pk, person_label(u)) for u in people]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Team.objects.filter(project=self.project, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This project already has a team with that name.")
        return name


class GuidelineForm(StyledFormMixin, forms.ModelForm):
    document = MediaAssetField(kinds=(MediaKind.DOCUMENT, MediaKind.IMAGE), label="Attached document (optional)")

    class Meta:
        model = Guideline
        fields = ["title", "version", "order", "content", "document"]
        widgets = {"content": forms.Textarea(attrs={"rows": 14, "class": "font-mono text-[13px]"})}
        help_texts = {"version": "Bump the version when rules change — employees are asked to acknowledge again."}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        bind_media_fields(self, user)


class OnboardingStepForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = OnboardingStep
        fields = ["step_type", "title", "description", "content", "tutorial", "test", "guideline"]
        widgets = {"content": forms.Textarea(attrs={"rows": 6})}
        labels = {"step_type": "Step type", "tutorial": "Linked tutorial", "test": "Linked test", "guideline": "Linked guideline"}
        help_texts = {
            "tutorial": "Done automatically when the video has really been watched.",
            "test": "Done automatically when the test is passed.",
        }

    def __init__(self, *args, project, **kwargs):
        """`project=None` → a company-wide step (every employee): only company-wide tutorials / tests can be
        linked, there are no guidelines and no final qualification (that is per project)."""
        super().__init__(*args, **kwargs)
        from django.db.models import Q

        self.project = project
        audience = Q(project__isnull=True) if project is None else Q(project=project) | Q(project__isnull=True)
        self.fields["tutorial"].queryset = Tutorial.objects.filter(audience).exclude(
            status=ContentStatus.ARCHIVED).order_by("title")
        self.fields["test"].queryset = Test.objects.filter(audience).exclude(
            status=ContentStatus.ARCHIVED).order_by("title")
        if project is None:
            del self.fields["guideline"]
            self.fields["step_type"].choices = [c for c in self.fields["step_type"].choices
                                                if c[0] != OnboardingStepType.QUALIFICATION]
            self.fields["tutorial"].help_text += " Only company-wide tutorials can be linked."
            self.fields["test"].help_text += " Only company-wide tests can be linked."
        else:
            self.fields["guideline"].queryset = project.guidelines.all()
            self.fields["guideline"].empty_label = "None"
        for name in ("tutorial", "test"):
            self.fields[name].empty_label = "None"

    def clean(self):
        data = super().clean()
        if data.get("tutorial") and data.get("test"):
            self.add_error("test", "Link either a tutorial or a test — a step is completed by one of them.")
        return data


# ── Training content ───────────────────────────────────────────────────────

class TutorialForm(StyledFormMixin, forms.ModelForm):
    video = MediaAssetField(kinds=(MediaKind.VIDEO,), label="Video")

    class Meta:
        model = Tutorial
        fields = ["title", "description", "category", "project", "cadence", "is_required", "video"]
        widgets = {"description": forms.Textarea(attrs={"rows": 6})}
        labels = {"is_required": "Required — assign automatically and track completion", "project": "Audience"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        set_project_field(self.fields["project"], user, allow_global=can_manage_content_for(user, None),
                          global_label="Company-wide (all employees)")
        self.fields["category"].empty_label = "No category"
        bind_media_fields(self, user)

    def clean_project(self):
        project = self.cleaned_data.get("project")
        if not can_manage_content_for(self.user, project):
            raise ValidationError("You can't manage content for this audience.")
        return project

    def clean_video(self):
        video = self.cleaned_data.get("video")
        if video is None and self.instance.pk and self.instance.is_published:
            raise ValidationError("A published tutorial needs a video. Unpublish first or choose another video.")
        return video


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TutorialCategory
        fields = ["name", "order"]

    def save(self, commit=True):
        obj = super().save(commit=False)
        base = slugify(obj.name)[:90] or "category"
        slug, n = base, 2
        while TutorialCategory.objects.filter(slug=slug).exclude(pk=obj.pk).exists():
            slug, n = f"{base}-{n}", n + 1
        obj.slug = slug
        if commit:
            obj.save()
        return obj


class FeedbackForm(StyledFormMixin, forms.ModelForm):
    video = MediaAssetField(kinds=(MediaKind.VIDEO,), label="Feedback video (optional)")
    due_at = forms.DateTimeField(required=False, input_formats=DATETIME_FORMATS, widget=datetime_widget(), label="Due (optional)")

    class Meta:
        model = Feedback
        fields = ["topic", "summary", "explanation", "project", "team", "severity", "cadence", "due_at", "video"]
        widgets = {
            "explanation": forms.Textarea(attrs={"rows": 9}),
            "team": ParentSelect(attrs={"data-depends-on": "project"}),
        }
        labels = {"explanation": "Explanation — the correct way to handle this type of task"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        set_project_field(self.fields["project"], user, allow_global=False)
        self.fields["team"].queryset = Team.objects.filter(project__in=self.fields["project"].queryset).order_by("name")
        self.fields["team"].label_from_instance = lambda t: t.name
        self.fields["team"].empty_label = "Whole project"
        bind_media_fields(self, user)
        # Once feedback has been delivered, its audience is fixed: recipients, their tracking rows and
        # the linked test all belong to that project / team.
        self.audience_locked = bool(self.instance.pk and (self.instance.is_published or self.instance.recipients.exists()))
        if self.audience_locked:
            for name in ("project", "team"):
                self.fields[name].disabled = True
            self.fields["project"].help_text = "Fixed once the feedback has been published."

    def clean(self):
        data = super().clean()
        project, team = data.get("project"), data.get("team")
        if project and not can_manage_content_for(self.user, project):
            self.add_error("project", "You can't manage feedback for this project.")
        if team and project and team.project_id != project.pk:
            self.add_error("team", "This team belongs to another project.")
        test = self.instance.test if self.instance.pk and self.instance.test_id else None
        if test is not None and project and test.project_id != project.pk:
            self.add_error("project", f"The linked test “{test.title}” belongs to another project — unlink it first.")
        return data


class TestForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Test
        fields = ["title", "description", "kind", "project", "passing_score", "attempt_limit", "time_limit_min",
                  "shuffle_questions", "reveal_answers"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        labels = {"passing_score": "Passing score (%)", "attempt_limit": "Attempt limit", "time_limit_min": "Time limit (minutes)",
                  "shuffle_questions": "Shuffle question order for each attempt", "reveal_answers": "Reveal correct answers after submission"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        set_project_field(self.fields["project"], user, allow_global=can_manage_content_for(user, None),
                          global_label="Company-wide")
        self.fields["passing_score"].widget.attrs.update(min=1, max=100)
        self.fields["attempt_limit"].widget.attrs.update(min=1)
        self.fields["time_limit_min"].widget.attrs.update(min=1)

    def clean_passing_score(self):
        value = self.cleaned_data["passing_score"]
        if not 1 <= value <= 100:
            raise ValidationError("Enter a percentage between 1 and 100.")
        return value

    def clean_attempt_limit(self):
        value = self.cleaned_data.get("attempt_limit")
        if value is not None and value < 1:
            raise ValidationError("Allow at least one attempt, or leave it empty for unlimited attempts.")
        return value

    def clean_time_limit_min(self):
        value = self.cleaned_data.get("time_limit_min")
        if value is not None and value < 1:
            raise ValidationError("Use at least 1 minute, or leave it empty for no time limit.")
        return value

    def clean_project(self):
        project = self.cleaned_data.get("project")
        if not can_manage_content_for(self.user, project):
            raise ValidationError("You can't manage tests for this audience.")
        return project


class QuestionForm(StyledFormMixin, forms.ModelForm):
    media = MediaAssetField(kinds=(MediaKind.IMAGE, MediaKind.VIDEO), label="Question image or video (optional)")
    tf_answer = forms.ChoiceField(choices=[("true", "True"), ("false", "False")], required=False,
                                  widget=forms.RadioSelect, label="Correct answer")

    class Meta:
        model = Question
        fields = ["qtype", "prompt", "explanation", "points", "media"]
        widgets = {"prompt": forms.Textarea(attrs={"rows": 3}), "explanation": forms.Textarea(attrs={"rows": 2})}
        labels = {"qtype": "Question type", "explanation": "Explanation (shown after submission)"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["points"].widget.attrs.update(min=1, max=100)
        bind_media_fields(self, user)
        if self.instance.pk and self.instance.qtype == QuestionType.TRUE_FALSE and not self.is_bound:
            correct = next((o for o in self.instance.options.all() if o.is_correct), None)
            if correct:
                self.initial["tf_answer"] = tf_key(correct.text) or "false"

    def clean_points(self):
        points = self.cleaned_data.get("points")
        if points is None or not 1 <= points <= 100:
            raise ValidationError("Give the question between 1 and 100 points.")
        return points


# True / False options are shown to employees, so new ones are written in Bangla. Older
# questions may still have English "True" / "False" options — both spellings are recognised.
TF_TEXT = {"true": "সত্য", "false": "মিথ্যা"}
_TF_KEYS = {"true": "true", "সত্য": "true", "false": "false", "মিথ্যা": "false"}


def tf_key(text) -> str | None:
    """'true' / 'false' for a True/False option text in either language, else None."""
    return _TF_KEYS.get((text or "").strip().lower())


class OptionForm(StyledFormMixin, forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    text = forms.CharField(max_length=500, required=False, widget=forms.TextInput(attrs={"placeholder": "Answer text"}))
    media = MediaAssetField(kinds=(MediaKind.IMAGE,))
    is_correct = forms.BooleanField(required=False, label="Correct")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        bind_media_fields(self, user)


OptionFormSet = forms.formset_factory(OptionForm, extra=0, can_delete=True, max_num=12, validate_max=True)


def clean_question(qform: QuestionForm, formset) -> list[dict] | None:
    """Validate the question + its option rows. Returns option dicts or None (errors added to the forms)."""
    ok_q = qform.is_valid()
    ok_o = formset.is_valid()
    if not ok_q:
        return None
    qtype = qform.cleaned_data["qtype"]
    if qtype == QuestionType.TRUE_FALSE:
        answer = qform.cleaned_data.get("tf_answer")
        if answer not in ("true", "false"):
            qform.add_error("tf_answer", "Choose whether the statement is true or false.")
            return None
        return [{"id": None, "tf": key, "text": TF_TEXT[key], "media": None, "is_correct": answer == key}
                for key in ("true", "false")]
    if not ok_o:
        return None
    options, errors = [], []
    for f in formset.forms:
        data = getattr(f, "cleaned_data", None) or {}
        if not data or data.get("DELETE"):
            continue
        text = (data.get("text") or "").strip()
        if not text and not data.get("media"):
            if data.get("is_correct"):
                errors.append("An option marked correct needs text or an image.")
            continue
        options.append({"id": data.get("id"), "text": text, "media": data.get("media"), "is_correct": bool(data.get("is_correct"))})
    correct = sum(1 for o in options if o["is_correct"])
    if len(options) < 2:
        errors.append("Add at least two answer options (text or image).")
    if correct < 1:
        errors.append("Mark at least one option as correct.")
    elif qtype == QuestionType.SINGLE_CHOICE and correct != 1:
        errors.append("A single-answer question needs exactly one correct option.")
    if errors:
        for e in dict.fromkeys(errors):
            qform.add_error(None, e)
        return None
    return options


# ── Communication ──────────────────────────────────────────────────────────

class AnnouncementForm(StyledFormMixin, forms.ModelForm):
    send_email = forms.BooleanField(required=False, label="Also send it by email", initial=False)

    class Meta:
        model = Announcement
        fields = ["title", "body", "project", "priority", "pinned"]
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}
        labels = {"project": "Audience", "pinned": "Pin to the top of the portal"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        set_project_field(self.fields["project"], user, allow_global=is_unscoped(user), global_label="Everyone (all employees)")
        if self.instance.pk:
            del self.fields["send_email"]

    def clean_project(self):
        project = self.cleaned_data.get("project")
        if not can_target_project(self.user, project):
            raise ValidationError("Choose one of your projects.")
        return project


class MeetingForm(StyledFormMixin, forms.ModelForm):
    AUDIENCE_PROJECT, AUDIENCE_SELECTED = "project", "selected"

    starts_at = forms.DateTimeField(input_formats=DATETIME_FORMATS, widget=datetime_widget(), label="Starts at")
    audience = forms.ChoiceField(
        choices=[(AUDIENCE_PROJECT, "Everyone in the project (or all employees)"), (AUDIENCE_SELECTED, "Selected employees")],
        initial=AUDIENCE_PROJECT, widget=forms.RadioSelect, label="Invitees",
    )
    invitees = PeopleChoiceField(queryset=User.objects.none(), required=False, label="Selected employees")

    class Meta:
        model = Meeting
        fields = ["title", "agenda", "meeting_url", "starts_at", "duration_min", "project"]
        widgets = {"agenda": forms.Textarea(attrs={"rows": 4})}
        labels = {"meeting_url": "Meeting link", "duration_min": "Duration (minutes)", "project": "Project"}
        help_texts = {"meeting_url": "Paste the Google Meet, Zoom or Microsoft Teams link."}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        set_project_field(self.fields["project"], user, allow_global=is_unscoped(user), global_label="Company-wide")
        self.fields["invitees"].queryset = assignable_people(user).order_by("name")
        self.fields["duration_min"].widget.attrs.update(min=5, max=600)
        if self.instance.pk:
            self.fields["audience"].initial = self.AUDIENCE_SELECTED
            self.fields["invitees"].initial = list(self.instance.invites.values_list("user_id", flat=True))

    def clean_project(self):
        project = self.cleaned_data.get("project")
        if not can_target_project(self.user, project):
            raise ValidationError("Choose one of your projects.")
        return project

    def clean_duration_min(self):
        value = self.cleaned_data.get("duration_min")
        if value is None or not 5 <= value <= 600:
            raise ValidationError("Use a duration between 5 and 600 minutes.")
        return value

    def clean_starts_at(self):
        value = self.cleaned_data.get("starts_at")
        if value and not self.instance.pk and value <= timezone.now():
            raise ValidationError("Choose a time in the future.")
        return value

    def clean(self):
        data = super().clean()
        if data.get("audience") == self.AUDIENCE_SELECTED and not data.get("invitees"):
            self.add_error("invitees", "Select at least one person, or invite the whole project.")
        return data


# ── Settings ────────────────────────────────────────────────────────────────

class CompanySettingsForm(StyledFormMixin, forms.Form):
    email = forms.EmailField(label="Main email")
    careers_email = forms.EmailField(label="Careers email", required=False)
    phone = forms.CharField(max_length=60, required=False)
    whatsapp = forms.CharField(label="WhatsApp number", max_length=60, required=False, help_text="International format, e.g. +8801700000000")
    address = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    business_hours = forms.CharField(max_length=120, required=False)
    show_map = forms.BooleanField(label="Show a map on the contact page", required=False)
    map_embed_url = forms.URLField(label="Map embed URL", max_length=1000, required=False,
                                   help_text="Google Maps → Share → Embed a map → copy the src URL.")
    linkedin = forms.URLField(label="LinkedIn URL", required=False)
    facebook = forms.URLField(label="Facebook URL", required=False)
    x = forms.URLField(label="X (Twitter) URL", required=False)
    youtube = forms.URLField(label="YouTube URL", required=False)

    def clean_map_embed_url(self):
        url = self.cleaned_data.get("map_embed_url", "")
        if url and not url.startswith("https://"):
            raise ValidationError("Use an https:// embed URL.")
        return url


class NotificationSettingsForm(StyledFormMixin, forms.Form):
    admin_emails = forms.CharField(
        label="Admin notification emails", required=False, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One per line (or comma separated). They receive new quote, application and signup alerts.",
    )

    def clean_admin_emails(self):
        raw = self.cleaned_data.get("admin_emails", "")
        emails = []
        for part in raw.replace(",", "\n").splitlines():
            part = part.strip().lower()
            if not part:
                continue
            try:
                validate_email(part)
            except ValidationError:
                raise ValidationError(f"“{part}” is not a valid email address.")
            if part not in emails:
                emails.append(part)
        return emails[:20]


class TestLinkForm(forms.Form):
    test = forms.ModelChoiceField(queryset=Test.objects.none())

    def __init__(self, *args, tests, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["test"].queryset = tests


TEST_KIND_CHOICES = TestKind.choices
