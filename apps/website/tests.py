"""Public website tests: pages, forms (records + emails), spam protection, SEO endpoints.

Run with:  DB_TEST_NAME=test_skyleon_web python manage.py test apps.website
"""

import json
import re
import shutil
import tempfile

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from apps.comms.models import EmailMessage
from apps.website import content
from apps.website.models import ContactMessage, JobApplication, QuoteRequest

TMP_STORAGE = tempfile.mkdtemp(prefix="website-tests-")

STATIC_PAGES = [
    "home", "services", "industries", "solutions", "capability", "quality", "platforms", "security", "about",
    "careers", "careers_thanks", "contact", "contact_thanks", "quote", "quote_thanks", "privacy", "terms",
]


def pdf(name="file.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4\n% test document\n", content_type="application/pdf")


def png(name="sample.png"):
    return SimpleUploadedFile(name, b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, content_type="image/png")


@override_settings(
    ADMIN_NOTIFICATION_EMAILS=["ops@example.com"],
    PRIVATE_STORAGE_DIR=TMP_STORAGE,
    STORAGE_BACKEND="local",
    EMAIL_SEND_IMMEDIATELY=False,
    APP_URL="https://www.brand.example",
)
class WebsiteTestCase(TestCase):
    def setUp(self):
        cache.clear()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_STORAGE, ignore_errors=True)


class PageTests(WebsiteTestCase):
    def assert_page(self, url):
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200, url)
        html = res.content.decode()
        self.assertEqual(len(re.findall(r"<h1[\s>]", html)), 1, f"{url} must have exactly one <h1>")
        self.assertRegex(html, r"<title>[^<]{10,}</title>")
        self.assertIn('<meta name="description" content="', html)
        self.assertIn(f'<link rel="canonical" href="https://www.brand.example{url.split("?")[0]}">', html)
        self.assertIn('property="og:title"', html)
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
            json.loads(block)  # valid JSON-LD
        return html

    def test_static_pages_render(self):
        for name in STATIC_PAGES:
            with self.subTest(page=name):
                self.assert_page(reverse(f"website:{name}"))

    def test_service_pages_render(self):
        for svc in content.SERVICES:
            with self.subTest(service=svc["slug"]):
                html = self.assert_page(reverse("website:service_detail", args=[svc["slug"]]))
                self.assertIn(escape(svc["h1"]), html)
                self.assertIn('"@type":"Service"', html)
                self.assertIn('"@type":"FAQPage"', html)
                self.assertIn('"@type":"BreadcrumbList"', html)
                self.assertIn(f'?type={svc["slug"]}', html)

    def test_solution_pages_render(self):
        for sp in content.SOLUTION_PAGES:
            with self.subTest(solution=sp["slug"]):
                html = self.assert_page(reverse("website:solution_detail", args=[sp["slug"]]))
                self.assertIn(escape(sp["h1"]), html)
                self.assertIn('"@type":"Service"', html)

    def test_unknown_slugs_404(self):
        self.assertEqual(self.client.get("/services/does-not-exist/").status_code, 404)
        self.assertEqual(self.client.get("/solutions/does-not-exist/").status_code, 404)

    def test_home_structured_data_and_navigation(self):
        html = self.client.get(reverse("website:home")).content.decode()
        self.assertIn("High-Quality AI Data Annotation, <span", html)
        for schema_type in ("Organization", "WebSite", "FAQPage"):
            self.assertIn(f'"@type":"{schema_type}"', html)
        for name in ("accounts:login", "accounts:client_login", "website:quote", "website:platforms", "website:security"):
            self.assertIn(f'href="{reverse(name)}"', html)
        for sp in content.SOLUTION_PAGES:  # footer lists every SEO landing page
            self.assertIn(reverse("website:solution_detail", args=[sp["slug"]]), html)

    def test_no_invented_claims(self):
        """Copy must not claim certifications or that we build models."""
        for name in ("home", "about", "security", "solutions"):
            html = self.client.get(reverse(f"website:{name}")).content.decode()
            for banned in ("ISO 27001", "SOC 2", "SOC2", "HIPAA", "GDPR certified", "testimonial"):
                self.assertNotIn(banned, html, f"{banned} found on {name}")

    def test_thank_you_pages_are_noindex(self):
        for name in ("quote_thanks", "contact_thanks", "careers_thanks"):
            html = self.client.get(reverse(f"website:{name}")).content.decode()
            self.assertIn('<meta name="robots" content="noindex, follow">', html)

    def test_health(self):
        self.assertEqual(self.client.get(reverse("website:health")).json(), {"status": "ok"})


class SeoEndpointTests(WebsiteTestCase):
    def test_robots_txt(self):
        res = self.client.get("/robots.txt")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res["Content-Type"].startswith("text/plain"))
        body = res.content.decode()
        for path in ("/portal/", "/admin/", "/client/", "/django-admin/", "/media/", "/account/", "/password/"):
            self.assertIn(f"Disallow: {path}", body)
        self.assertIn("Sitemap: https://www.brand.example/sitemap.xml", body)

    def test_sitemap_uses_app_url(self):
        res = self.client.get("/sitemap.xml")
        self.assertEqual(res.status_code, 200)
        self.assertIn("xml", res["Content-Type"])
        body = res.content.decode()
        self.assertIn("<loc>https://www.brand.example/</loc>", body)
        self.assertIn("<loc>https://www.brand.example/request-a-quote/</loc>", body)
        for svc in content.SERVICES:
            self.assertIn(f"<loc>https://www.brand.example/services/{svc['slug']}/</loc>", body)
        for sp in content.SOLUTION_PAGES:
            self.assertIn(f"<loc>https://www.brand.example/solutions/{sp['slug']}/</loc>", body)
        self.assertNotIn("thank-you", body)
        self.assertNotIn("testserver", body)


class QuoteFormTests(WebsiteTestCase):
    url = "/request-a-quote/"

    def data(self, **extra):
        return {
            "name": "Jane Cooper", "company": "Example Robotics", "email": "jane@example.com", "phone": "+1 555 010 2000",
            "project_type": "Video annotation", "annotation_types": ["Object tracking", "Action segmentation"],
            "dataset_size": "150 hours of video", "timeline": "Within 1 month", "platform": "CVAT",
            "requirements": "Egocentric kitchen videos, 12 action classes.", "source": "from /services/video-annotation/",
            **extra,
        }

    def test_prefills_project_type_from_query(self):
        html = self.client.get(self.url + "?type=action-description").content.decode()
        self.assertIn('<option value="Action description" selected>', html)
        html = self.client.get(self.url + "?type=robotic-task-annotation").content.decode()
        self.assertIn('<option value="Action &amp; activity annotation" selected>', html)

    def test_valid_submission_creates_lead_and_queues_emails(self):
        res = self.client.post(self.url, self.data(attachment=pdf("brief.pdf")), REMOTE_ADDR="203.0.113.7")
        self.assertRedirects(res, reverse("website:quote_thanks"))
        q = QuoteRequest.objects.get()
        self.assertEqual(q.project_type, "Video annotation")
        self.assertEqual(q.annotation_types, ["Object tracking", "Action segmentation"])
        self.assertEqual(q.source, "from /services/video-annotation/")
        self.assertEqual(q.ip_address, "203.0.113.7")
        self.assertIsNotNone(q.attachment)
        self.assertEqual(q.attachment.purpose, "quote")
        admin_mail = EmailMessage.objects.get(to="ops@example.com")
        self.assertEqual(admin_mail.template, "quote_admin")
        self.assertIn("New quote request", admin_mail.subject)
        self.assertIn(reverse("backoffice:lead_detail", args=[q.pk]), admin_mail.html)
        client_mail = EmailMessage.objects.get(to="jane@example.com")
        self.assertEqual(client_mail.template, "quote_confirmation")
        self.assertEqual(client_mail.subject, "We've received your request")

    def test_missing_required_fields(self):
        res = self.client.post(self.url, self.data(name="", email="not-an-email", project_type=""))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "field-error")
        self.assertFalse(QuoteRequest.objects.exists())
        self.assertFalse(EmailMessage.objects.exists())

    def test_rejects_disallowed_file_type(self):
        bad = SimpleUploadedFile("tool.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        res = self.client.post(self.url, self.data(attachment=bad))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "file type isn")
        self.assertFalse(QuoteRequest.objects.exists())

    def test_rejects_file_content_mismatch(self):
        fake = SimpleUploadedFile("brief.pdf", b"this is not a pdf", content_type="application/pdf")
        res = self.client.post(self.url, self.data(attachment=fake))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "does not match its extension")
        self.assertFalse(QuoteRequest.objects.exists())

    def test_honeypot_silently_discards(self):
        res = self.client.post(self.url, self.data(website_url="http://spam.example"))
        self.assertRedirects(res, reverse("website:quote_thanks"))
        self.assertFalse(QuoteRequest.objects.exists())
        self.assertFalse(EmailMessage.objects.exists())

    def test_rate_limit(self):
        for _ in range(5):
            self.assertEqual(self.client.post(self.url, self.data(), REMOTE_ADDR="198.51.100.9").status_code, 302)
        res = self.client.post(self.url, self.data(), REMOTE_ADDR="198.51.100.9")
        self.assertEqual(res.status_code, 429)
        self.assertContains(res, "several requests in a short time", status_code=429)
        self.assertEqual(QuoteRequest.objects.count(), 5)
        # another IP is unaffected
        self.assertEqual(self.client.post(self.url, self.data(), REMOTE_ADDR="198.51.100.10").status_code, 302)


class ContactFormTests(WebsiteTestCase):
    url = "/contact/"

    def data(self, **extra):
        return {
            "name": "Sam Lee", "email": "sam@example.com", "company": "Lab", "phone": "",
            "subject": "Partnership", "message": "We would like to discuss a long-term project.", **extra,
        }

    def test_valid_submission(self):
        res = self.client.post(self.url, self.data())
        self.assertRedirects(res, reverse("website:contact_thanks"))
        m = ContactMessage.objects.get()
        self.assertEqual(m.subject, "Partnership")
        admin_mail = EmailMessage.objects.get(to="ops@example.com")
        self.assertEqual(admin_mail.template, "contact_admin")
        self.assertIn(reverse("backoffice:message_detail", args=[m.pk]), admin_mail.html)
        self.assertEqual(EmailMessage.objects.get(to="sam@example.com").template, "contact_confirmation")

    def test_validation(self):
        res = self.client.post(self.url, self.data(message="hi", phone="call me"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "at least 10 characters")
        self.assertContains(res, "valid phone number")
        self.assertFalse(ContactMessage.objects.exists())

    def test_honeypot(self):
        res = self.client.post(self.url, self.data(website_url="x"))
        self.assertRedirects(res, reverse("website:contact_thanks"))
        self.assertFalse(ContactMessage.objects.exists())

    def test_rate_limit(self):
        for _ in range(5):
            self.client.post(self.url, self.data(), REMOTE_ADDR="192.0.2.1")
        res = self.client.post(self.url, self.data(), REMOTE_ADDR="192.0.2.1")
        self.assertEqual(res.status_code, 429)
        self.assertEqual(ContactMessage.objects.count(), 5)


class CareersFormTests(WebsiteTestCase):
    url = "/careers/"

    def data(self, **extra):
        return {
            "full_name": "Amal Perera", "email": "amal@example.com", "phone": "+94 77 123 4567", "location": "Colombo, Sri Lanka",
            "experience": "1 – 2 years", "annotation_experience": "CVAT bounding boxes and video tracking.",
            "preferred_work_type": "Remote — full-time", "availability": "Within 2 weeks",
            "skills": ["Bounding boxes", "Video annotation"], "other_skills": "Sinhala, Tamil, bounding boxes",
            "portfolio_url": "https://portfolio.example/amal", "consent": "on", **extra,
        }

    def test_valid_application(self):
        res = self.client.post(self.url, self.data(cv=pdf("cv.pdf"), sample=png()))
        self.assertRedirects(res, reverse("website:careers_thanks"))
        app = JobApplication.objects.get()
        self.assertEqual(app.skills, ["Bounding boxes", "Video annotation", "Sinhala", "Tamil"])
        self.assertEqual(app.cv.purpose, "cv")
        self.assertEqual(app.sample.purpose, "sample")
        self.assertEqual(app.preferred_work_type, "Remote — full-time")
        admin_mail = EmailMessage.objects.get(to="ops@example.com")
        self.assertEqual(admin_mail.template, "application_admin")
        self.assertIn("New job application", admin_mail.subject)
        self.assertIn(reverse("backoffice:applicant_detail", args=[app.pk]), admin_mail.html)
        confirmation = EmailMessage.objects.get(to="amal@example.com")
        self.assertEqual((confirmation.template, confirmation.subject), ("application_confirmation", "Application received"))

    def test_thank_you_message(self):
        res = self.client.get(reverse("website:careers_thanks"))
        self.assertContains(
            res,
            "Application received. Our team will review your information and contact you if your profile "
            "matches an available project.",
        )
        self.assertContains(res, reverse("accounts:signup"))

    def test_cv_and_consent_required(self):
        data = self.data()
        data.pop("consent")
        res = self.client.post(self.url, data)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Please confirm so we can process your application.")
        self.assertEqual(res.context["form"].errors["cv"], ["This field is required."])
        self.assertFalse(JobApplication.objects.exists())

    def test_cv_must_be_document(self):
        res = self.client.post(self.url, self.data(cv=png("cv.png")))
        self.assertEqual(res.status_code, 200)
        self.assertIn("cv", res.context["form"].errors)
        self.assertFalse(JobApplication.objects.exists())

    def test_cv_size_limit(self):
        big = SimpleUploadedFile("cv.pdf", b"%PDF" + b"0" * (10 * 1024 * 1024 + 1), content_type="application/pdf")
        res = self.client.post(self.url, self.data(cv=big))
        self.assertEqual(res.status_code, 200)
        self.assertIn("too large", res.context["form"].errors["cv"][0])

    def test_honeypot(self):
        res = self.client.post(self.url, self.data(cv=pdf("cv.pdf"), website_url="spam"))
        self.assertRedirects(res, reverse("website:careers_thanks"))
        self.assertFalse(JobApplication.objects.exists())
