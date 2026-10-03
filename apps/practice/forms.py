import math

from django import forms
from django.db.models import Q

from apps.core.forms import StyledFormMixin
from apps.projects.models import Project
from apps.storage.models import MediaAsset, MediaKind, MediaStatus

from .config import ACTION_LABELS, CUT_MODES
from .models import PracticeTask


def parse_time(value: str) -> float:
    """Accepts seconds (75.5) or mm:ss(.ms) / hh:mm:ss."""
    value = (value or "").strip()
    if not value:
        raise ValueError("empty")
    parts = value.split(":")
    if len(parts) > 3:
        raise ValueError("bad time")
    total = 0.0
    for p in parts:
        number = float(p)
        if not math.isfinite(number) or number < 0:
            raise ValueError("bad time")
        total = total * 60 + number
    if not math.isfinite(total):
        raise ValueError("bad time")
    return total


class TimeField(forms.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("help_text", "Seconds or mm:ss, e.g. 01:15")
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, (int, float)):
            m, s = divmod(float(value), 60)
            return f"{int(m):02d}:{s:05.2f}".rstrip("0").rstrip(".")
        return value

    def to_python(self, value):
        value = super().to_python(value)
        if value in (None, ""):
            return None
        try:
            return round(parse_time(value), 3)
        except ValueError:
            raise forms.ValidationError("Enter seconds (e.g. 75) or mm:ss (e.g. 01:15).")


def video_choices(user, current=None):
    """
    READY videos the user may pick for a practice task: videos of tutorials / feedback / practice
    tasks in their project scope (company-wide content included), videos they uploaded themselves,
    and the task's current video. Never every file in storage (CVs, other projects' videos …).
    """
    qs = MediaAsset.objects.filter(kind=MediaKind.VIDEO, status=MediaStatus.READY)
    if user is None:
        return qs.filter(pk=current) if current else qs.none()
    from apps.backoffice.media import content_assets_q

    cond = content_assets_q(user)
    if current:
        cond |= Q(pk=current)
    return qs.filter(cond).order_by("-created_at")


class PracticeTaskForm(StyledFormMixin, forms.ModelForm):
    range_start = TimeField(label="Hands present from", required=False)
    range_end = TimeField(label="Hands present until", required=False, help_text="Empty = end of video")
    video = forms.ModelChoiceField(
        queryset=MediaAsset.objects.none(), required=False, label="Video",
        help_text="Upload a new video below, or pick one that is already uploaded (tutorials / feedback).",
    )

    class Meta:
        model = PracticeTask
        fields = ["title", "project", "instructions", "video", "range_start", "range_end", "tolerance_sec", "passing_score", "order"]
        widgets = {"instructions": forms.Textarea(attrs={"rows": 5})}
        labels = {"tolerance_sec": "Boundary tolerance (seconds)", "passing_score": "Passing score (%)", "order": "Sort order"}

    def __init__(self, *args, user=None, projects=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects if projects is not None else Project.objects.all()
        self.fields["project"].empty_label = "All employees (company-wide)"
        self.fields["video"].queryset = video_choices(user, current=self.instance.video_id if self.instance else None)
        self.fields["passing_score"].widget.attrs.update(min=1, max=100)
        self.fields["video"].label_from_instance = lambda a: f"{a.original_name or a.pk} · {int(a.duration_sec or 0) // 60:02d}:{int(a.duration_sec or 0) % 60:02d}"
        if self.instance and self.instance.pk:
            self.initial.setdefault("range_start", self.instance.range_start)
            if self.instance.range_end is not None:
                self.initial.setdefault("range_end", self.instance.range_end)

    def clean(self):
        data = super().clean()
        start, end = data.get("range_start") or 0, data.get("range_end")
        data["range_start"] = start
        video = data.get("video")
        if end is not None and end <= start:
            self.add_error("range_end", "Must be after the start.")
        if video and video.duration_sec and start >= video.duration_sec:
            self.add_error("range_start", "Starts after the end of the video.")
        tol = data.get("tolerance_sec")
        if tol is not None and not (0 < tol <= 10):
            self.add_error("tolerance_sec", "Use a value between 0.05 and 10 seconds.")
        return data

    def clean_passing_score(self):
        value = self.cleaned_data.get("passing_score")
        if value is None or not 1 <= value <= 100:
            raise forms.ValidationError("Enter a percentage between 1 and 100.")
        return value


class ToolSettingsForm(StyledFormMixin, forms.Form):
    cut_mode = forms.ChoiceField(label="N key behaviour", choices=list(CUT_MODES.items()), widget=forms.RadioSelect)
    speeds = forms.CharField(label="Speed steps", help_text="Comma separated, cycled by the Speed button, e.g. 1, 1.5, 2, 0.5")
    frame_rate = forms.IntegerField(label="Frame rate for frame stepping", min_value=1, max_value=240)

    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        config = config or {}
        for action, label in ACTION_LABELS.items():
            self.fields[f"key_{action}"] = forms.CharField(
                label=label, required=False,
                initial=", ".join(config.get("shortcuts", {}).get(action, [])),
            )
        self.fields["cut_mode"].initial = config.get("cut_mode", "toggle")
        self.fields["speeds"].initial = ", ".join(str(s) for s in config.get("speeds", [1, 1.5, 2]))
        self.fields["frame_rate"].initial = config.get("frame_rate", 30)

    def clean_speeds(self):
        try:
            speeds = [float(s) for s in self.cleaned_data["speeds"].split(",") if s.strip()]
        except ValueError:
            raise forms.ValidationError("Use numbers separated by commas.")
        if not speeds or any(s <= 0 or s > 4 for s in speeds):
            raise forms.ValidationError("Speeds must be between 0.1 and 4.")
        return speeds

    def to_config(self):
        d = self.cleaned_data
        shortcuts = {
            action: [k.strip() for k in (d.get(f"key_{action}") or "").split(",") if k.strip()]
            for action in ACTION_LABELS
        }
        return {"cut_mode": d["cut_mode"], "speeds": d["speeds"], "frame_rate": d["frame_rate"], "shortcuts": shortcuts}
