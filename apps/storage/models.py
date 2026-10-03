import uuid

from django.conf import settings
from django.db import models


class MediaKind(models.TextChoices):
    VIDEO = "video", "Video"
    IMAGE = "image", "Image"
    DOCUMENT = "document", "Document"


class MediaProvider(models.TextChoices):
    LOCAL = "local", "Server storage"
    S3 = "s3", "Object storage (S3-compatible)"
    EXTERNAL = "external", "External URL / streaming service"


class MediaStatus(models.TextChoices):
    UPLOADING = "uploading", "Uploading"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class MediaAsset(models.Model):
    """
    Metadata for a stored file. The bytes live in object storage (or the private
    storage folder in local mode) — never in the database or public_html.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=MediaKind.choices)
    provider = models.CharField(max_length=20, choices=MediaProvider.choices)
    storage_key = models.CharField(max_length=500, blank=True)
    external_url = models.URLField(max_length=1000, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=MediaStatus.choices, default=MediaStatus.UPLOADING)
    purpose = models.CharField(max_length=40, blank=True)  # tutorial | feedback | question | option | cv | quote | thumbnail …
    thumbnail = models.OneToOneField("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="thumbnail_of")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="uploaded_media")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_name or str(self.id)

    @property
    def is_ready(self) -> bool:
        return self.status == MediaStatus.READY

    @property
    def is_hls(self) -> bool:
        return (self.external_url or "").split("?")[0].endswith(".m3u8")
