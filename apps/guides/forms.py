import json

from django import forms
from django.utils.text import slugify

from apps.core.forms import StyledFormMixin
from apps.core.icons import ICONS
from apps.projects.models import Project

from . import services
from .importer import clean_actions
from .models import Guide, GuideSection, GuideStep
from .video import clean_url, parse_start


class GuideForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Guide
        fields = ["title", "title_en", "slug", "summary", "kind", "project", "icon", "accent", "source_url", "order"]
        widgets = {"summary": forms.Textarea(attrs={"rows": 2})}
        labels = {"title": "Title (Bangla)", "summary": "Summary (Bangla)", "order": "Sort order"}

    def __init__(self, *args, projects=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects if projects is not None else Project.objects.all()
        self.fields["project"].empty_label = "All employees (company-wide)"
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Address of the guide: /portal/guides/<slug>/. Leave empty to generate it from the English title."
        self.fields["icon"].widget.attrs["list"] = "guide-icons"
        self.fields["title"].widget.attrs["lang"] = "bn"
        self.fields["summary"].widget.attrs["lang"] = "bn"

    def clean_icon(self):
        icon = (self.cleaned_data.get("icon") or "").strip()
        if icon not in ICONS:
            raise forms.ValidationError("Unknown icon. Pick one from the list (e.g. scissors, file-text, book-open-check).")
        return icon

    def clean(self):
        data = super().clean()
        slug = (data.get("slug") or "").strip()
        if not slug:
            base = slugify(data.get("title_en") or "") or slugify(data.get("title") or "") or "guide"
            slug, n = base[:110], 2
            while Guide.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
                slug = f"{base[:110]}-{n}"
                n += 1
            data["slug"] = slug
            self.instance.slug = slug
        return data


class SectionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = GuideSection
        fields = ["title", "title_en", "anchor", "intro"]
        widgets = {"intro": forms.Textarea(attrs={"rows": 5, "lang": "bn"})}
        labels = {"title": "Title (Bangla)", "intro": "Introduction (Bangla, Markdown)"}

    def __init__(self, *args, guide=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.guide = guide
        self.fields["anchor"].required = False
        self.fields["anchor"].help_text = "Deep link id (#anchor). Leave empty to generate it."
        self.fields["title"].widget.attrs["lang"] = "bn"

    def clean(self):
        data = super().clean()
        taken = services.taken_anchors(self.guide, exclude=self.instance)
        anchor = services.clean_anchor(data.get("anchor"))
        if anchor:
            if anchor in taken:
                self.add_error("anchor", "Already used by another section or step of this guide.")
        else:
            number = self.guide.sections.exclude(pk=self.instance.pk).count() + 1
            anchor = services.unique_anchor(
                services.section_anchor_base(data.get("title_en") or "", data.get("title") or "", number), taken, f"section-{number}")
        data["anchor"] = anchor
        return data


class StepForm(StyledFormMixin, forms.ModelForm):
    video_start = forms.CharField(label="Start at", required=False, help_text="Seconds (90) or m:ss (1:30)")
    actions = forms.CharField(
        label="Which button does what", required=False, widget=forms.Textarea(attrs={"rows": 4, "spellcheck": "false"}),
        help_text='JSON list: [{"key": "N", "label_bn": "…", "description_bn": "…"}]',
    )

    class Meta:
        model = GuideStep
        fields = ["section", "title", "anchor", "body", "body_en", "video_url", "video_caption", "video_start", "actions", "estimated_minutes"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 14, "lang": "bn"}),
            "body_en": forms.Textarea(attrs={"rows": 6, "lang": "en"}),
        }
        labels = {"title": "Title (Bangla)", "body": "Explanation (Bangla, Markdown)", "video_caption": "Video caption (Bangla)",
                  "estimated_minutes": "Reading time (minutes)"}

    def __init__(self, *args, guide=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.guide = guide
        self.fields["section"].queryset = guide.sections.all()
        self.fields["section"].empty_label = None
        self.fields["section"].label_from_instance = lambda s: s.title
        self.fields["anchor"].required = False
        self.fields["anchor"].help_text = "Deep link id (#anchor). Leave empty to generate it."
        self.fields["title"].widget.attrs["lang"] = "bn"
        self.fields["video_caption"].widget.attrs["lang"] = "bn"
        self.fields["video_url"].widget.attrs.update({"placeholder": "https://…", "data-video-url": ""})
        self.fields["estimated_minutes"].help_text = "Optional — estimated from the text length when empty."
        if self.instance.pk:
            self.initial["actions"] = json.dumps(self.instance.actions or [], ensure_ascii=False, indent=1)
            self.initial["video_start"] = self.instance.video_start if self.instance.video_start is not None else ""
        else:
            self.initial.setdefault("actions", "[]")

    def clean_video_url(self):
        url = (self.cleaned_data.get("video_url") or "").strip()
        if url and clean_url(url) is None:
            raise forms.ValidationError("Use an http(s) link to the original video.")
        return url

    def clean_video_start(self):
        raw = (self.cleaned_data.get("video_start") or "").strip()
        if not raw:
            return None
        value = parse_start(raw)
        if value is None:
            raise forms.ValidationError("Enter seconds (e.g. 90) or m:ss (e.g. 1:30).")
        return value

    def clean_actions(self):
        raw = (self.cleaned_data.get("actions") or "").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise forms.ValidationError(f"Invalid JSON: {e}")
        if isinstance(data, list):  # drop rows left completely empty in the editor
            data = [r for r in data if not (isinstance(r, dict) and not any(
                str(r.get(k) or "").strip() for k in ("key", "label_bn", "description_bn")))]
        errors = []
        rows = clean_actions(data, "actions", errors)
        if errors:
            raise forms.ValidationError(errors)
        return rows

    def clean(self):
        data = super().clean()
        section = data.get("section")
        if section is None:
            return data
        taken = services.taken_anchors(self.guide, exclude=self.instance)
        anchor = services.clean_anchor(data.get("anchor"))
        if anchor:
            if anchor in taken:
                self.add_error("anchor", "Already used by another section or step of this guide.")
        else:
            number = section.steps.exclude(pk=self.instance.pk).count() + 1
            anchor = services.unique_anchor(
                services.step_anchor_base(section.anchor, data.get("title") or "", number), taken, f"{section.anchor}-{number}")
        data["anchor"] = anchor
        return data


class ImportForm(StyledFormMixin, forms.Form):
    file = forms.FileField(label="Guide JSON file", required=False, widget=forms.ClearableFileInput(attrs={"accept": ".json,application/json"}))
    text = forms.CharField(label="…or paste the JSON", required=False, widget=forms.Textarea(attrs={"rows": 10, "spellcheck": "false"}))
    replace = forms.BooleanField(label="Replace existing content (keeps employees' progress on steps whose anchors still exist)", required=False)
    publish = forms.BooleanField(label="Publish after import", required=False)
    dry_run = forms.BooleanField(label="Validate only (dry run — nothing is saved)", required=False)

    def clean(self):
        data = super().clean()
        f = data.get("file")
        if f:
            if f.size > 5 * 1024 * 1024:
                raise forms.ValidationError("The file is too large (max 5 MB).")
            data["raw"] = f.read()
        elif (data.get("text") or "").strip():
            data["raw"] = data["text"]
        else:
            raise forms.ValidationError("Choose a JSON file or paste the JSON.")
        return data
