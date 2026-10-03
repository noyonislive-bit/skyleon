import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, User, UserStatus

from .models import MediaAsset, MediaStatus
from .services import media_url, store_uploaded_file


class StorageTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(PRIVATE_STORAGE_DIR=self.tmp, STORAGE_BACKEND="local", UPLOAD_CHUNK_SIZE=4)
        self.override.enable()
        from . import backends

        backends._backends.clear()
        self.trainer = User.objects.create_user("t@example.com", "pw-Strong-1", name="T", role=Role.TRAINER, status=UserStatus.ACTIVE)
        self.employee = User.objects.create_user("e@example.com", "pw-Strong-1", name="E", status=UserStatus.ACTIVE)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post_json(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json")

    def test_chunked_upload_and_ranged_stream(self):
        self.client.force_login(self.trainer)
        payload = b"0123456789abcdef"
        r = self.post_json(reverse("storage:upload_init"), {"filename": "clip.mp4", "size": len(payload), "mime_type": "video/mp4", "kind": "video", "purpose": "tutorial"})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(data["mode"], "chunked")
        for offset in range(0, len(payload), 4):
            r = self.client.post(data["url"], payload[offset:offset + 4], content_type="application/octet-stream", HTTP_X_CHUNK_OFFSET=str(offset))
            self.assertEqual(r.status_code, 200)
        # out-of-order chunk is rejected
        r = self.client.post(data["url"], b"zz", content_type="application/octet-stream", HTTP_X_CHUNK_OFFSET="3")
        self.assertEqual(r.status_code, 409)
        r = self.post_json(reverse("storage:upload_complete", args=[data["id"]]), {"duration": 12.5, "width": 640, "height": 360})
        self.assertEqual(r.status_code, 200, r.content)
        asset = MediaAsset.objects.get(pk=data["id"])
        self.assertEqual(asset.status, MediaStatus.READY)
        self.assertEqual(asset.duration_sec, 12.5)

        # stream is bound to the viewer and supports Range
        url = media_url(asset, self.employee)
        self.client.force_login(self.employee)
        r = self.client.get(url, HTTP_RANGE="bytes=2-5")
        self.assertEqual(r.status_code, 206)
        self.assertEqual(b"".join(r.streaming_content), b"2345")
        self.assertEqual(r["Content-Range"], "bytes 2-5/16")
        self.client.force_login(self.trainer)
        self.assertEqual(self.client.get(url).status_code, 404)  # someone else's signed URL
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(url.replace("t=", "t=x")).status_code, 404)

    def test_employees_cannot_upload(self):
        self.client.force_login(self.employee)
        r = self.post_json(reverse("storage:upload_init"), {"filename": "a.mp4", "size": 10, "kind": "video"})
        self.assertEqual(r.status_code, 403)

    def test_rejects_disallowed_types_and_fake_content(self):
        self.client.force_login(self.trainer)
        r = self.post_json(reverse("storage:upload_init"), {"filename": "evil.exe", "size": 10, "kind": "video"})
        self.assertEqual(r.status_code, 400)
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            store_uploaded_file(SimpleUploadedFile("cv.pdf", b"MZ not a pdf", content_type="application/pdf"), purpose="cv")
        asset = store_uploaded_file(SimpleUploadedFile("cv.pdf", b"%PDF-1.4 hello", content_type="application/pdf"), purpose="cv")
        self.assertEqual(asset.status, MediaStatus.READY)
