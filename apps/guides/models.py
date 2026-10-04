"""
Work guides — long work documents (e.g. "Video splitting", "Description writing")
rebuilt as step-by-step Bangla training: Guide → sections → steps.

Each step has a Bangla explanation (Markdown with callouts), an optional link to
the ORIGINAL video (embedded from its source, never downloaded or re-hosted) and
a "which button does what" table. Employees mark steps as understood
(GuideProgress) and see their progress per guide.

Source of truth (docs/GUIDES.md): original document → original video → actual
workflow → Bangla text → portal UI. Every step and Task Error example records
where it comes from (source_ref, the video segment it matches) and is marked
"verified" by a trainer once the Bangla text was checked against the original
document AND video. Editing the text or the video segment clears the mark.
"""

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.choices import ContentStatus


class GuideKind(models.TextChoices):
    VIDEO_SPLITTING = "video_splitting", "Video splitting"
    DESCRIPTION = "description", "Description / text writing"
    GENERAL = "general", "General"


KIND_LABELS_BN = {
    GuideKind.VIDEO_SPLITTING: "ভিডিও স্প্লিটিং",
    GuideKind.DESCRIPTION: "ডেসক্রিপশন লেখা",
    GuideKind.GENERAL: "সাধারণ নির্দেশনা",
}


class GuideAccent(models.TextChoices):
    BRAND = "brand", "Green (brand)"
    CYAN = "cyan", "Cyan"
    EMERALD = "emerald", "Emerald"
    AMBER = "amber", "Amber"
    ROSE = "rose", "Rose"
    VIOLET = "violet", "Violet"


class Guide(models.Model):
    title = models.CharField(max_length=200, help_text="Bangla title shown to employees")
    title_en = models.CharField("English title", max_length=200, blank=True, help_text="Title of the original English document (optional)")
    slug = models.SlugField(max_length=120, unique=True, help_text="Used in the address, e.g. video-splitting")
    summary = models.CharField(max_length=500, blank=True, help_text="One or two Bangla sentences shown on the guide card")
    icon = models.CharField(max_length=40, default="book-open-check", help_text="Lucide icon name, e.g. scissors, file-text")
    accent = models.CharField(max_length=20, choices=GuideAccent.choices, default=GuideAccent.BRAND)
    kind = models.CharField(max_length=30, choices=GuideKind.choices, default=GuideKind.GENERAL, db_index=True)
    source_url = models.URLField("Original document link", max_length=500, blank=True, help_text="Shown to staff only")
    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="guides",
        help_text="Leave empty to make it available to every employee",
    )
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.DRAFT, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("guides:detail", args=[self.slug])

    @property
    def is_published(self):
        return self.status == ContentStatus.PUBLISHED

    @property
    def kind_label_bn(self):
        return KIND_LABELS_BN.get(self.kind, "")

    def publish(self, save=True):
        self.status = ContentStatus.PUBLISHED
        self.published_at = self.published_at or timezone.now()
        if save:
            self.save(update_fields=["status", "published_at", "updated_at"])


class GuideSection(models.Model):
    guide = models.ForeignKey(Guide, on_delete=models.CASCADE, related_name="sections")
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200, help_text="Bangla section title")
    title_en = models.CharField("English title", max_length=200, blank=True)
    anchor = models.SlugField(max_length=120, help_text="Used for deep links (#anchor). Unique within the guide.")
    intro = models.TextField(blank=True, help_text="Optional Bangla introduction (Markdown)")

    class Meta:
        ordering = ["order", "pk"]
        constraints = [models.UniqueConstraint(fields=["guide", "anchor"], name="guides_section_anchor_unique")]

    def __str__(self):
        return self.title


class GuideStep(models.Model):
    # Denormalised from section.guide so anchors can be unique per guide and
    # progress can be counted per guide without joins.
    guide = models.ForeignKey(Guide, on_delete=models.CASCADE, related_name="steps", editable=False)
    section = models.ForeignKey(GuideSection, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200, help_text="Bangla step title")
    anchor = models.SlugField(max_length=120, help_text="Used for deep links (#anchor). Unique within the guide.")
    body = models.TextField(blank=True, help_text="Bangla explanation (Markdown, callouts for rules / tips / warnings)")
    body_en = models.TextField("Original English text", blank=True)
    video_url = models.URLField("Original video link", max_length=1000, blank=True,
                                help_text="The ORIGINAL link (YouTube, Vimeo, Drive, Loom, Stream/SharePoint, Lark, MP4, HLS). Never re-hosted.")
    video_asset = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                    help_text="A video uploaded to our storage (used instead of the link when set)")
    video_caption = models.CharField(max_length=300, blank=True)
    video_start = models.PositiveIntegerField(null=True, blank=True, help_text="Start the video at this second (optional)")
    video_end = models.PositiveIntegerField(null=True, blank=True, help_text="End of the part of the video this step explains (optional)")
    actions = models.JSONField(default=list, blank=True, help_text='[{"key": "N", "label_bn": "…", "description_bn": "…"}]')
    estimated_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    source_ref = models.CharField("Source in the original", max_length=300, blank=True,
                                  help_text="Where this step comes from, e.g. “Doc §2 Splitting rules, point 3 · video 01:20–02:05”. Staff only.")
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Changing any of these means the Bangla text must be checked against the original again.
    VERIFIED_FIELDS = ("title", "body", "body_en", "video_url", "video_asset_id", "video_start", "video_end", "actions")

    @property
    def has_video(self):
        return bool(self.video_url or self.video_asset_id)

    class Meta:
        ordering = ["section__order", "section_id", "order", "pk"]
        constraints = [models.UniqueConstraint(fields=["guide", "anchor"], name="guides_step_anchor_unique")]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.section_id and not self.guide_id:
            self.guide_id = self.section.guide_id
        elif self.section_id and self.section.guide_id != self.guide_id:
            self.guide_id = self.section.guide_id
        super().save(*args, **kwargs)


class GuideTaskError(models.Model):
    """
    A Task Error example from the original document or video: a concrete mistake that makes
    the task count as a Task Error, shown to employees as its own clearly marked card —
    what went wrong, why it is wrong, how to avoid it and the correct method — next to the
    part of the ORIGINAL video that shows it. Attached to the step it belongs to (or to the
    whole guide when it is general).
    """

    guide = models.ForeignKey(Guide, on_delete=models.CASCADE, related_name="task_errors", editable=False)
    step = models.ForeignKey(GuideStep, null=True, blank=True, on_delete=models.CASCADE, related_name="task_errors",
                             help_text="The step this mistake belongs to. Empty = a general example for the whole guide.")
    order = models.PositiveIntegerField(default=0)
    anchor = models.SlugField(max_length=120, help_text="Used for deep links (#anchor). Unique within the guide.")
    title = models.CharField(max_length=200, help_text="Short Bangla name of the mistake")
    what_wrong = models.TextField("What went wrong", help_text="Bangla (Markdown): exactly what was done wrong")
    why_wrong = models.TextField("Why it is wrong", blank=True, help_text="Bangla (Markdown): which rule it breaks and why")
    how_to_avoid = models.TextField("How to avoid it", blank=True, help_text="Bangla (Markdown): what to check while working")
    correct_method = models.TextField("Correct method", blank=True, help_text="Bangla (Markdown): the right way, as the original shows it")
    video_url = models.URLField("Original video link", max_length=1000, blank=True,
                                help_text="The ORIGINAL video that shows this mistake (never re-hosted)")
    video_asset = models.ForeignKey("storage.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                    help_text="A video uploaded to our storage (used instead of the link when set)")
    video_start = models.PositiveIntegerField(null=True, blank=True)
    video_end = models.PositiveIntegerField(null=True, blank=True)
    video_caption = models.CharField(max_length=300, blank=True)
    source_ref = models.CharField("Source in the original", max_length=300, blank=True,
                                  help_text="Where the original shows it, e.g. “Video 2 at 03:10” or “Doc §4 Task Error list”. Staff only.")
    source_text_en = models.TextField("Original English text", blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    VERIFIED_FIELDS = ("title", "what_wrong", "why_wrong", "how_to_avoid", "correct_method",
                       "video_url", "video_asset_id", "video_start", "video_end", "source_text_en")

    @property
    def has_video(self):
        return bool(self.video_url or self.video_asset_id)

    class Meta:
        ordering = ["order", "pk"]
        constraints = [models.UniqueConstraint(fields=["guide", "anchor"], name="guides_task_error_anchor_unique")]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.step_id:
            self.guide_id = self.step.guide_id
        super().save(*args, **kwargs)


class GuideProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="guide_progress")
    step = models.ForeignKey(GuideStep, on_delete=models.CASCADE, related_name="progress")
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-read_at"]
        constraints = [models.UniqueConstraint(fields=["user", "step"], name="guides_progress_user_step_unique")]

    def __str__(self):
        return f"{self.user} · {self.step}"
