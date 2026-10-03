import json
import os
import re

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import has_permission

from .backends import SIGNING_SALT, get_backend
from .models import MediaAsset, MediaKind, MediaProvider, MediaStatus
from .services import create_external, create_pending_upload, media_url

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _can_upload(user):
    return has_permission(user, "content.manage") or has_permission(user, "projects.manage")


def _json(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _asset_payload(asset, user):
    thumb = asset.thumbnail if asset.thumbnail_id else None
    return {
        "id": str(asset.pk),
        "kind": asset.kind,
        "status": asset.status,
        "name": asset.original_name,
        "size": asset.size_bytes,
        "duration": asset.duration_sec,
        "url": media_url(asset, user),
        "thumbnail_url": media_url(thumb, user) if thumb else "",
    }


@require_POST
def upload_init(request):
    """Step 1: register an upload and get the target (presigned PUT or chunk endpoint)."""
    if not _can_upload(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)
    data = _json(request)
    kind = data.get("kind") if data.get("kind") in MediaKind.values else MediaKind.VIDEO
    try:
        asset = create_pending_upload(
            filename=str(data.get("filename") or "upload"),
            size=int(data.get("size") or 0),
            mime_type=str(data.get("mime_type") or ""),
            kind=kind,
            purpose=str(data.get("purpose") or kind)[:40],
            user=request.user,
        )
    except (ValidationError, ValueError) as exc:
        return JsonResponse({"error": "; ".join(getattr(exc, "messages", [str(exc)]))}, status=400)
    target = get_backend(asset.provider).upload_target(asset)
    return JsonResponse({"id": str(asset.pk), **target})


@require_POST
def upload_chunk(request, asset_id):
    """Local backend only: append one chunk (raw body) at X-Chunk-Offset."""
    if not _can_upload(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)
    asset = get_object_or_404(MediaAsset, pk=asset_id, status=MediaStatus.UPLOADING, provider=MediaProvider.LOCAL)
    if asset.uploaded_by_id != request.user.pk:
        return JsonResponse({"error": "forbidden"}, status=403)
    try:
        offset = int(request.headers.get("X-Chunk-Offset", "0"))
        received = get_backend("local").append(asset.storage_key, request.body, offset)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    if asset.size_bytes and received > asset.size_bytes:
        return JsonResponse({"error": "too much data"}, status=400)
    return JsonResponse({"received": received})


@require_POST
def upload_complete(request, asset_id):
    """Step 3: verify the object landed in storage and store client-side metadata."""
    if not _can_upload(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)
    asset = get_object_or_404(MediaAsset, pk=asset_id, status=MediaStatus.UPLOADING)
    if asset.uploaded_by_id != request.user.pk:
        return JsonResponse({"error": "forbidden"}, status=403)
    data = _json(request)
    actual = get_backend(asset.provider).size(asset.storage_key)
    if not actual:
        asset.status = MediaStatus.FAILED
        asset.save(update_fields=["status"])
        return JsonResponse({"error": "upload not found in storage"}, status=400)
    asset.size_bytes = actual
    for field, cast in (("duration_sec", float), ("width", int), ("height", int)):
        value = data.get(field.replace("_sec", ""))
        if value not in (None, ""):
            try:
                setattr(asset, field, cast(value))
            except (TypeError, ValueError):
                pass
    thumb_id = data.get("thumbnail_id")
    if thumb_id:
        thumb = MediaAsset.objects.filter(pk=thumb_id, kind=MediaKind.IMAGE, uploaded_by=request.user).first()
        if thumb:
            asset.thumbnail = thumb
    asset.status = MediaStatus.READY
    asset.save()
    return JsonResponse(_asset_payload(asset, request.user))


@require_POST
def external_create(request):
    """Register an external HLS (.m3u8) or MP4 URL from a streaming provider."""
    if not _can_upload(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)
    data = _json(request)
    try:
        duration = float(data["duration"]) if data.get("duration") else None
        asset = create_external(url=str(data.get("url") or "").strip(), purpose=str(data.get("purpose") or "video")[:40],
                                user=request.user, duration=duration)
    except (ValidationError, ValueError) as exc:
        return JsonResponse({"error": "; ".join(getattr(exc, "messages", [str(exc)]))}, status=400)
    return JsonResponse(_asset_payload(asset, request.user))


@require_GET
def asset_info(request, asset_id):
    if not _can_upload(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)
    asset = get_object_or_404(MediaAsset, pk=asset_id)
    return JsonResponse(_asset_payload(asset, request.user))


@require_GET
def preview(request, asset_id):
    """Staff-only: redirect to a fresh signed URL (used by the admin panel)."""
    if not (_can_upload(request.user) or has_permission(request.user, "applicants.manage") or has_permission(request.user, "leads.manage")):
        raise Http404
    asset = get_object_or_404(MediaAsset, pk=asset_id, status=MediaStatus.READY)
    return redirect(media_url(asset, request.user, download=request.GET.get("download") == "1"))


@require_GET
def stream(request, asset_id):
    """Serve a locally stored file with a signed token and HTTP Range support (video seeking)."""
    token = request.GET.get("t", "")
    try:
        payload = signing.loads(token, salt=SIGNING_SALT, max_age=settings.MEDIA_URL_TTL_SECONDS)
    except signing.BadSignature:
        raise Http404
    if payload.get("a") != str(asset_id):
        raise Http404
    if payload.get("u") is not None and (not request.user.is_authenticated or payload["u"] != request.user.pk):
        raise Http404  # signed URLs are bound to the viewer's session
    asset = get_object_or_404(MediaAsset, pk=asset_id, provider=MediaProvider.LOCAL, status=MediaStatus.READY)
    path = get_backend("local").path(asset.storage_key)
    if not path.exists():
        raise Http404
    size = path.stat().st_size
    content_type = asset.mime_type or "application/octet-stream"
    download = request.GET.get("download") == "1"
    disposition = f'{"attachment" if download else "inline"}; filename="{os.path.basename(asset.original_name or path.name)}"'

    range_header = request.headers.get("Range", "")
    match = RANGE_RE.match(range_header) if range_header else None
    if not match:
        response = FileResponse(open(path, "rb"), content_type=content_type)
        response["Content-Length"] = str(size)
        response["Accept-Ranges"] = "bytes"
        response["Content-Disposition"] = disposition
        response["Cache-Control"] = "private, max-age=3600"
        return response

    start_s, end_s = match.groups()
    if start_s == "":
        length = int(end_s or 0)
        start, end = max(0, size - length), size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else min(start + 8 * 1024 * 1024, size) - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        resp = HttpResponse(status=416)
        resp["Content-Range"] = f"bytes */{size}"
        return resp

    def iterator(chunk=64 * 1024):
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = fh.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    response = StreamingHttpResponse(iterator(), status=206, content_type=content_type)
    response["Content-Length"] = str(end - start + 1)
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = disposition
    response["Cache-Control"] = "private, max-age=3600"
    return response
