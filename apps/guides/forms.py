import json

from django import forms
from django.utils.text import slugify

from apps.core.forms import StyledFormMixin
from apps.core.icons import ICONS
from apps.projects.models import Project

from . import services
from .importer import clean_actions
from .models import Guide, GuideKind, GuideSection, GuideStep, GuideTaskError
from .video import clean_url, parse_start

VIDEO_SOURCES = [("link", "Original link"), ("upload", "Uploaded video")]


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


def _media_field():
    from apps.backoffice.forms import MediaAssetField

    return MediaAssetField(label="Uploaded video", required=False)


class SegmentMixin:
    """video_start / video_end typed as seconds or m:ss — the part of the ORIGINAL video the text describes."""

    def _seconds(self, name):
        raw = (self.cleaned_data.get(name) or "").strip()
        if not raw:
            return None
        value = parse_start(raw)
        if value is None:
            raise forms.ValidationError("Enter seconds (e.g. 90) or m:ss (e.g. 1:30).")
        return value

    def clean_video_start(self):
        return self._seconds("video_start")

    def clean_video_end(self):
        return self._seconds("video_end")

    def clean_video_url(self):
        url = (self.cleaned_data.get("video_url") or "").strip()
        if url and clean_url(url) is None:
            raise forms.ValidationError("Use an http(s) link to the original video.")
        return url

    def check_segment(self, data):
        start, end = data.get("video_start"), data.get("video_end")
        if end is not None and end <= (start or 0):
            self.add_error("video_end", "The end must be after the start.")
        # One video per item: the original link OR a video uploaded to our storage.
        if data.get("video_source") == "upload":
            if not data.get("video_asset") and not self.has_error("video_asset"):
                self.add_error("video_asset", "Upload a video or pick one, or switch to “Original link”.")
            data["video_url"] = ""
            self.instance.video_url = ""
        else:
            data["video_asset"] = None
            self.instance.video_asset = None

    def init_video(self, user):
        from apps.backoffice.forms import bind_media_fields

        bind_media_fields(self, user)
        self.initial.setdefault("video_source", "upload" if getattr(self.instance, "video_asset_id", None) else "link")
        self.fields["video_url"].required = False

    def init_segment(self):
        for name in ("video_start", "video_end"):
            value = getattr(self.instance, name, None) if self.instance.pk else None
            if value is not None:
                self.initial[name] = f"{value // 60}:{value % 60:02d}"


class StepForm(SegmentMixin, StyledFormMixin, forms.ModelForm):
    video_source = forms.ChoiceField(choices=VIDEO_SOURCES, widget=forms.RadioSelect, required=False, initial="link")
    video_asset = _media_field()
    video_start = forms.CharField(label="Video part — from", required=False, help_text="Seconds (90) or m:ss (1:30)")
    video_end = forms.CharField(label="Video part — to", required=False,
                                help_text="Where the part this step explains ends (optional)")
    actions = forms.CharField(
        label="Which button does what", required=False, widget=forms.Textarea(attrs={"rows": 4, "spellcheck": "false"}),
        help_text='JSON list: [{"key": "N", "label_bn": "…", "description_bn": "…"}]',
    )

    class Meta:
        model = GuideStep
        fields = ["section", "title", "anchor", "body", "body_en", "video_url", "video_asset", "video_caption", "video_start",
                  "video_end", "actions", "estimated_minutes", "source_ref"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 14, "lang": "bn"}),
            "body_en": forms.Textarea(attrs={"rows": 6, "lang": "en"}),
        }
        labels = {"title": "Title (Bangla)", "body": "Explanation (Bangla, Markdown)", "video_caption": "Video caption (Bangla)",
                  "estimated_minutes": "Reading time (minutes)"}

    def __init__(self, *args, guide=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.guide = guide
        self.init_video(user)
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
        else:
            self.initial.setdefault("actions", "[]")
        self.init_segment()

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
        self.check_segment(data)
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


class TaskErrorForm(SegmentMixin, StyledFormMixin, forms.ModelForm):
    video_source = forms.ChoiceField(choices=VIDEO_SOURCES, widget=forms.RadioSelect, required=False, initial="link")
    video_asset = _media_field()
    video_start = forms.CharField(label="Video part — from", required=False, help_text="Seconds (90) or m:ss (1:30)")
    video_end = forms.CharField(label="Video part — to", required=False, help_text="Where the mistake ends in the video (optional)")

    class Meta:
        model = GuideTaskError
        fields = ["step", "title", "anchor", "what_wrong", "why_wrong", "how_to_avoid", "correct_method",
                  "video_url", "video_asset", "video_caption", "video_start", "video_end", "source_ref", "source_text_en"]
        widgets = {
            "what_wrong": forms.Textarea(attrs={"rows": 4, "lang": "bn"}),
            "why_wrong": forms.Textarea(attrs={"rows": 4, "lang": "bn"}),
            "how_to_avoid": forms.Textarea(attrs={"rows": 4, "lang": "bn"}),
            "correct_method": forms.Textarea(attrs={"rows": 4, "lang": "bn"}),
            "source_text_en": forms.Textarea(attrs={"rows": 4, "lang": "en"}),
        }
        labels = {
            "title": "Mistake (short Bangla title)",
            "what_wrong": "কী ভুল হয়েছে — What went wrong",
            "why_wrong": "কেন ভুল — Why it is wrong",
            "how_to_avoid": "কীভাবে এড়াবেন — How to avoid it",
            "correct_method": "সঠিক পদ্ধতি — Correct method",
            "video_caption": "Video caption (Bangla)",
        }

    def __init__(self, *args, guide=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.guide = guide
        self.init_video(user)
        self.fields["step"].queryset = GuideStep.objects.filter(guide=guide).select_related("section").order_by(
            "section__order", "section_id", "order", "pk")
        self.fields["step"].empty_label = "— General example for the whole guide —"
        self.fields["step"].label_from_instance = lambda st: f"{st.section.title} › {st.title}"
        self.fields["anchor"].required = False
        self.fields["anchor"].help_text = "Deep link id (#anchor). Leave empty to generate it."
        self.fields["video_url"].widget.attrs.update({"placeholder": "https://…"})
        for name in ("title", "video_caption"):
            self.fields[name].widget.attrs["lang"] = "bn"
        self.init_segment()

    def clean(self):
        data = super().clean()
        self.check_segment(data)
        taken = services.taken_anchors(self.guide, exclude=self.instance)
        anchor = services.clean_anchor(data.get("anchor"))
        if anchor:
            if anchor in taken:
                self.add_error("anchor", "Already used by a section, step or another example of this guide.")
        else:
            step = data.get("step")
            siblings = GuideTaskError.objects.filter(guide=self.guide, step=step).exclude(pk=self.instance.pk).count()
            anchor = services.unique_anchor(services.error_anchor_base(step.anchor if step else None, siblings + 1),
                                            taken, f"task-error-{siblings + 1}")
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


class DocumentImportForm(StyledFormMixin, forms.Form):
    file = forms.FileField(label="Word (.docx) or Markdown (.md) file",
                           widget=forms.ClearableFileInput(attrs={"accept": ".docx,.md,.markdown,.txt"}),
                           help_text="In Lark / Feishu: open the document → ⋯ → Download as → Word (or Markdown).")
    title = forms.CharField(label="Guide title (Bangla)", max_length=200, required=False,
                            help_text="Optional — you can set it later. The document's own title is kept as the English title.")
    slug = forms.SlugField(label="Address (slug)", max_length=110, required=False,
                           help_text="e.g. video-splitting. Leave empty to generate it from the document title.")
    kind = forms.ChoiceField(choices=GuideKind.choices, initial=GuideKind.GENERAL)
    project = forms.ModelChoiceField(queryset=Project.objects.none(), required=False, empty_label="All employees (company-wide)")
    source_url = forms.URLField(label="Original document link", max_length=500, required=False,
                                help_text="The Lark link — shown to staff next to the guide so everyone can check the original.")
    dry_run = forms.BooleanField(label="Preview the structure only (nothing is saved)", required=False)

    def __init__(self, *args, projects=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects if projects is not None else Project.objects.all()
        self.fields["title"].widget.attrs["lang"] = "bn"

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > 20 * 1024 * 1024:
            raise forms.ValidationError("The file is too large (max 20 MB).")
        if not f.name.lower().endswith((".docx", ".md", ".markdown", ".txt")):
            raise forms.ValidationError("Upload a Word (.docx) or Markdown (.md) file.")
        return f

