"""High-level helpers for creating and serving MediaAssets."""

import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .backends import get_backend, guess_mime
from .models import MediaAsset, MediaKind, MediaProvider, MediaStatus

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
DOCUMENT_EXTS = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".zip", ".csv", ".xlsx", ".json", ".xml"}

ALLOWED = {MediaKind.VIDEO: VIDEO_EXTS, MediaKind.IMAGE: IMAGE_EXTS, MediaKind.DOCUMENT: DOCUMENT_EXTS | IMAGE_EXTS}

MAGIC = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF8"],
    ".zip": [b"PK\x03\x04"],
    ".docx": [b"PK\x03\x04"],
    ".xlsx": [b"PK\x03\x04"],
    ".odt": [b"PK\x03\x04"],
    ".doc": [b"\xd0\xcf\x11\xe0"],
}


def build_key(purpose: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()[:10]
    now = timezone.now()
    return f"{purpose or 'misc'}/{now:%Y/%m}/{uuid.uuid4().hex}{ext}"


def validate_upload(filename: str, size: int, kind: str, max_mb: int | None = None) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED.get(kind, set()):
        raise ValidationError(f"File type {ext or '(none)'} is not allowed.")
    limit = max_mb or (settings.MAX_VIDEO_UPLOAD_MB if kind == MediaKind.VIDEO else settings.MAX_DOCUMENT_UPLOAD_MB)
    if size and size > limit * 1024 * 1024:
        raise ValidationError(f"File is too large (max {limit} MB).")
    return ext


def store_uploaded_file(uploaded, *, kind=MediaKind.DOCUMENT, purpose="", user=None, max_mb=None) -> MediaAsset:
    """Save a file received through a normal Django form (CVs, quote attachments, images)."""
    ext = validate_upload(uploaded.name, uploaded.size, kind, max_mb)
    head = uploaded.read(8)
    uploaded.seek(0)
    signatures = MAGIC.get(ext)
    if signatures and not any(head.startswith(sig) for sig in signatures):
        raise ValidationError("The file content does not match its extension.")
    backend = get_backend()
    key = build_key(purpose, uploaded.name)
    mime = _trusted_mime(uploaded.name, kind)
    size = backend.save(key, uploaded, mime)
    return MediaAsset.objects.create(
        kind=kind, provider=backend.name, storage_key=key, mime_type=mime, size_bytes=size or uploaded.size,
        original_name=os.path.basename(uploaded.name)[:255], status=MediaStatus.READY, purpose=purpose,
        uploaded_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _trusted_mime(filename: str, kind: str) -> str:
    """MIME type from the (already validated) extension — the browser-supplied type is ignored."""
    mime = guess_mime(filename)
    if kind == MediaKind.VIDEO and not mime.startswith("video/"):
        return "video/mp4"
    if kind == MediaKind.IMAGE and not mime.startswith("image/"):
        return "application/octet-stream"
    return mime


def create_pending_upload(*, filename, size, mime_type, kind, purpose, user) -> MediaAsset:
    validate_upload(filename, size, kind)
    backend = get_backend()
    return MediaAsset.objects.create(
        kind=kind, provider=backend.name, storage_key=build_key(purpose, filename),
        mime_type=_trusted_mime(filename, kind), size_bytes=size, original_name=os.path.basename(filename)[:255],
        status=MediaStatus.UPLOADING, purpose=purpose, uploaded_by=user,
    )


def create_external(*, url, kind=MediaKind.VIDEO, purpose="", user=None, duration=None) -> MediaAsset:
    if not url.startswith("https://") and not (settings.DEBUG and url.startswith("http://")):
        raise ValidationError("External media must use an https:// URL.")
    return MediaAsset.objects.create(
        kind=kind, provider=MediaProvider.EXTERNAL, external_url=url, status=MediaStatus.READY, purpose=purpose,
        original_name=url.rsplit("/", 1)[-1][:255], uploaded_by=user, duration_sec=duration,
        mime_type="application/x-mpegURL" if url.split("?")[0].endswith(".m3u8") else guess_mime(url.split("?")[0], "video/mp4"),
    )


def media_url(asset: MediaAsset | None, user, *, download=False) -> str:
    """Signed, expiring URL for an asset. Call only after checking the user may see the parent object."""
    if asset is None or asset.status != MediaStatus.READY:
        return ""
    if asset.provider == MediaProvider.EXTERNAL:
        return asset.external_url
    return get_backend(asset.provider).read_url(asset, user, download=download)


def delete_asset(asset: MediaAsset) -> None:
    if asset.storage_key and asset.provider != MediaProvider.EXTERNAL:
        try:
            get_backend(asset.provider).delete(asset.storage_key)
        except Exception:
            pass
    asset.delete()
