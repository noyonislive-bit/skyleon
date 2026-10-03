"""
Storage backends for private files.

LocalBackend  — files under PRIVATE_STORAGE_DIR (outside public_html). Uploads
                arrive in chunks through Django; playback is streamed through a
                signed, expiring URL with HTTP Range support.
S3Backend     — any S3-compatible bucket. Browsers upload directly with a
                presigned PUT and stream directly with presigned GET URLs, so
                video traffic never touches the shared-hosting server.
"""

import mimetypes
import os
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.urls import reverse

SIGNING_SALT = "storage.stream"


class BaseBackend:
    name = ""

    def upload_target(self, asset) -> dict:
        raise NotImplementedError

    def save(self, key: str, fileobj, content_type: str = "") -> int:
        raise NotImplementedError

    def size(self, key: str) -> int | None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def read_url(self, asset, user, *, download=False, ttl=None) -> str:
        raise NotImplementedError


class LocalBackend(BaseBackend):
    name = "local"

    @property
    def root(self) -> Path:
        return Path(settings.PRIVATE_STORAGE_DIR).resolve()

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("Invalid storage key")
        return p

    def upload_target(self, asset) -> dict:
        return {
            "mode": "chunked",
            "url": reverse("storage:upload_chunk", args=[asset.pk]),
            "chunk_size": settings.UPLOAD_CHUNK_SIZE,
        }

    def save(self, key, fileobj, content_type="") -> int:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(p, "wb") as fh:
            chunks = fileobj.chunks() if hasattr(fileobj, "chunks") else iter(lambda: fileobj.read(1024 * 1024), b"")
            for chunk in chunks:
                fh.write(chunk)
                written += len(chunk)
        return written

    def append(self, key, data: bytes, offset: int) -> int:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        current = p.stat().st_size if p.exists() else 0
        if offset != current:
            raise ValueError(f"Unexpected offset {offset}, expected {current}")
        with open(p, "ab") as fh:
            fh.write(data)
        return current + len(data)

    def size(self, key):
        p = self.path(key)
        return p.stat().st_size if p.exists() else None

    def delete(self, key):
        try:
            os.remove(self.path(key))
        except FileNotFoundError:
            pass

    def read_url(self, asset, user, *, download=False, ttl=None) -> str:
        token = signing.dumps({"a": str(asset.pk), "u": user.pk if user else None}, salt=SIGNING_SALT, compress=True)
        url = reverse("storage:stream", args=[asset.pk]) + f"?t={token}"
        return url + "&download=1" if download else url


class S3Backend(BaseBackend):
    name = "s3"

    def __init__(self):
        import boto3
        from botocore.config import Config

        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region_name=settings.S3_REGION or None,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4", s3={"addressing_style": settings.S3_ADDRESSING_STYLE}),
        )

    def upload_target(self, asset) -> dict:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": asset.storage_key, "ContentType": asset.mime_type or "application/octet-stream"},
            ExpiresIn=60 * 60 * 6,
        )
        return {"mode": "put", "url": url, "headers": {"Content-Type": asset.mime_type or "application/octet-stream"}}

    def save(self, key, fileobj, content_type="") -> int:
        extra = {"ContentType": content_type} if content_type else {}
        if hasattr(fileobj, "seek"):
            fileobj.seek(0)
        self.client.upload_fileobj(fileobj, self.bucket, key, ExtraArgs=extra)
        return self.size(key) or 0

    def size(self, key):
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except Exception:
            return None

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def read_url(self, asset, user, *, download=False, ttl=None) -> str:
        params = {"Bucket": self.bucket, "Key": asset.storage_key}
        if download:
            params["ResponseContentDisposition"] = f'attachment; filename="{asset.original_name or "file"}"'
        return self.client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=ttl or settings.MEDIA_URL_TTL_SECONDS
        )


_backends = {}


def get_backend(name: str | None = None) -> BaseBackend:
    name = name or settings.STORAGE_BACKEND
    if name not in _backends:
        _backends[name] = S3Backend() if name == "s3" else LocalBackend()
    return _backends[name]


def guess_mime(filename: str, fallback="application/octet-stream") -> str:
    return mimetypes.guess_type(filename)[0] or fallback
