"""Public website forms: quote request, contact, job application."""

import os
import re

from django import forms

from apps.core.forms import HoneypotMixin, StyledFormMixin
from apps.core.site_settings import BRAND

from . import content

CV_EXTS = (".pdf", ".doc", ".docx")
SAMPLE_EXTS = (".pdf", ".doc", ".docx", ".zip", ".jpg", ".jpeg", ".png", ".webp")
QUOTE_EXTS = (
    ".pdf", ".doc", ".docx", ".zip", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".csv", ".json", ".xml", ".xlsx",
)
CV_MAX_MB = 10
SAMPLE_MAX_MB = 10
QUOTE_MAX_MB = 15

PHONE_RE = re.compile(r"^[+()\d\s.\-/]{6,40}$")


def _choices(values, blank=None):
    choices = [(v, v) for v in values]
    return [("", blank)] + choices if blank else choices


def check_upload(f, exts, max_mb):
    """Friendly extension + size validation before the file reaches storage."""
    if not f:
        return f
    ext = os.path.splitext(f.name or "")[1].lower()
    if ext not in exts:
        nice = ", ".join(e.lstrip(".").upper() for e in exts)
        raise forms.ValidationError(f"This file type isn't supported. Please upload one of: {nice}.")
    if f.size > max_mb * 1024 * 1024:
        raise forms.ValidationError(f"This file is too large — the maximum is {max_mb} MB.")
    if f.size == 0:
        raise forms.ValidationError("The uploaded file is empty.")
    return f


def clean_phone_value(value, required=False):
    value = (value or "").strip()
    if not value:
        if required:
            raise forms.ValidationError("Please enter a phone number.")
        return ""
    if not PHONE_RE.match(value) or len(re.sub(r"\D", "", value)) < 6:
        raise forms.ValidationError("Please enter a valid phone number (digits, spaces, + and - only).")
    return value


class QuoteForm(StyledFormMixin, HoneypotMixin, forms.Form):
    name = forms.CharField(label="Full name", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Jane Cooper"}))
    company = forms.CharField(label="Company", max_length=200, required=False, widget=forms.TextInput(attrs={"autocomplete": "organization", "placeholder": "Company or institution"}))
    email = forms.EmailField(label="Work email", widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@company.com"}))
    phone = forms.CharField(label="Phone", max_length=40, required=False, widget=forms.TextInput(attrs={"autocomplete": "tel", "placeholder": "Optional"}))
    project_type = forms.ChoiceField(label="Project type", choices=_choices(content.PROJECT_TYPES, "Select a project type"))
    annotation_types = forms.MultipleChoiceField(
        label="Annotation type", required=False, choices=_choices(content.ANNOTATION_TYPES),
        widget=forms.CheckboxSelectMultiple, help_text="Select all that apply.",
    )
    dataset_size = forms.CharField(
        label="Estimated dataset size", max_length=100, required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. 20,000 images or 150 hours of video"}),
    )
    timeline = forms.ChoiceField(label="Expected timeline", required=False, choices=_choices(content.TIMELINE_CHOICES, "Select a timeline"))
    platform = forms.ChoiceField(label="Preferred platform", required=False, choices=_choices(content.PLATFORM_CHOICES, "Select a platform"))
    requirements = forms.CharField(
        label="Additional requirements", max_length=5000, required=False,
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Use case, classes / actions to label, guideline status, output format, QA expectations…"}),
    )
    attachment = forms.FileField(
        label="File / sample upload", required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ",".join(QUOTE_EXTS), "data-max-mb": QUOTE_MAX_MB}),
        help_text=f"Optional · PDF, DOC/DOCX, ZIP, images, CSV, JSON, XML or XLSX · max {QUOTE_MAX_MB} MB",
    )
    source = forms.CharField(required=False, max_length=200, widget=forms.HiddenInput)

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get("phone"))

    def clean_attachment(self):
        return check_upload(self.cleaned_data.get("attachment"), QUOTE_EXTS, QUOTE_MAX_MB)

    def clean_source(self):
        return (self.cleaned_data.get("source") or "")[:200]


class ContactForm(StyledFormMixin, HoneypotMixin, forms.Form):
    name = forms.CharField(label="Full name", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    company = forms.CharField(label="Company", max_length=200, required=False, widget=forms.TextInput(attrs={"autocomplete": "organization"}))
    phone = forms.CharField(label="Phone", max_length=40, required=False, widget=forms.TextInput(attrs={"autocomplete": "tel"}))
    subject = forms.CharField(label="Subject", max_length=200, required=False, widget=forms.TextInput(attrs={"placeholder": "How can we help?"}))
    message = forms.CharField(
        label="Message", max_length=5000, min_length=10,
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "Tell us a little about your question or project."}),
        error_messages={"min_length": "Please write a little more (at least 10 characters)."},
    )

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get("phone"))


class ApplicationForm(StyledFormMixin, HoneypotMixin, forms.Form):
    full_name = forms.CharField(label="Full name", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    phone = forms.CharField(label="Phone", max_length=40, widget=forms.TextInput(attrs={"autocomplete": "tel"}))
    location = forms.CharField(label="Location", max_length=120, widget=forms.TextInput(attrs={"placeholder": "City, country", "autocomplete": "address-level2"}))
    experience = forms.ChoiceField(label="Experience", choices=_choices(content.EXPERIENCE_CHOICES, "Select your experience"))
    annotation_experience = forms.CharField(
        label="Annotation experience", max_length=3000, required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Projects, data types, tools and annotation types you have worked with (if any)."}),
    )
    preferred_work_type = forms.ChoiceField(label="Preferred work type", choices=_choices(content.WORK_TYPE_CHOICES, "Select a work type"))
    availability = forms.ChoiceField(label="Availability", choices=_choices(content.AVAILABILITY_CHOICES, "When can you start?"))
    skills = forms.MultipleChoiceField(label="Skills", required=False, choices=_choices(content.SKILL_CHOICES), widget=forms.CheckboxSelectMultiple)
    other_skills = forms.CharField(
        label="Other skills", max_length=300, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Languages, tools or other relevant skills (comma-separated)"}),
    )
    cv = forms.FileField(
        label="CV", help_text=f"PDF, DOC or DOCX · max {CV_MAX_MB} MB",
        widget=forms.ClearableFileInput(attrs={"accept": ",".join(CV_EXTS), "data-max-mb": CV_MAX_MB}),
    )
    portfolio_url = forms.URLField(
        label="Portfolio / sample link", max_length=500, required=False, assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://…"}),
    )
    sample = forms.FileField(
        label="Sample file", required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ",".join(SAMPLE_EXTS), "data-max-mb": SAMPLE_MAX_MB}),
        help_text=f"Optional · PDF, DOC/DOCX, ZIP or image · max {SAMPLE_MAX_MB} MB",
    )
    consent = forms.BooleanField(
        label=f"I agree that {BRAND['name']} may store and use my information to evaluate my application.",
        error_messages={"required": "Please confirm so we can process your application."},
    )

    def clean_full_name(self):
        return self.cleaned_data["full_name"].strip()

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get("phone"), required=True)

    def clean_cv(self):
        return check_upload(self.cleaned_data.get("cv"), CV_EXTS, CV_MAX_MB)

    def clean_sample(self):
        return check_upload(self.cleaned_data.get("sample"), SAMPLE_EXTS, SAMPLE_MAX_MB)

    def skills_list(self):
        skills = list(self.cleaned_data.get("skills") or [])
        for extra in (self.cleaned_data.get("other_skills") or "").split(","):
            extra = extra.strip()[:60]
            if extra and extra.lower() not in {s.lower() for s in skills}:
                skills.append(extra)
        return skills[:30]
