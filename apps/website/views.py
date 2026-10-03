"""Public marketing website."""

import ipaddress
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_GET

from apps.comms.services import absolute_url, notify_admins, send_email
from apps.core import ratelimit, site_settings
from apps.storage.models import MediaKind
from apps.storage.services import delete_asset, store_uploaded_file

from . import content as c
from . import seo
from .forms import ApplicationForm, ContactForm, QuoteForm
from .models import ContactMessage, JobApplication, QuoteRequest
from .sitemaps import SITEMAPS

logger = logging.getLogger(__name__)

BRAND = site_settings.BRAND["name"]
RATE_LIMIT_MESSAGE = (
    "You've sent several requests in a short time. Please wait a little while and try again — "
    "or email us directly at {email}."
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def page(request, template, *, title, description, crumbs=None, schema=(), status=200, **ctx):
    """Render a public page with meta, breadcrumbs and JSON-LD."""
    full_title = title if BRAND in title else f"{title} | {BRAND}"
    objects = list(schema)
    crumb_ld = seo.breadcrumb_list(crumbs, request.path)
    if crumb_ld:
        objects.append(crumb_ld)
    ctx.update(
        meta={"title": full_title, "description": description},
        crumbs=crumbs or [],
        jsonld=seo.ld(*objects),
    )
    return render(request, template, ctx, status=status)


def _services(slugs):
    return [c.SERVICE_BY_SLUG[s] for s in slugs if s in c.SERVICE_BY_SLUG]


def _solution_pages(slugs):
    return [c.SOLUTION_PAGE_BY_SLUG[s] for s in slugs if s in c.SOLUTION_PAGE_BY_SLUG]


def _ip(request):
    raw = ratelimit.client_ip(request)
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def _review_url(name, pk):
    try:
        return absolute_url(reverse(name, args=[pk]))
    except NoReverseMatch:  # admin panel not wired yet
        return ""


def _rate_limited(request, scope, limit=5, window=3600):
    return ratelimit.hit(f"{scope}:{ratelimit.client_ip(request)}", limit, window)


def _rate_message():
    return RATE_LIMIT_MESSAGE.format(email=site_settings.company().get("email") or "our team")


def _is_spam(form):
    return "website_url" in form.errors


def _store(file, purpose, max_mb):
    if not file:
        return None
    return store_uploaded_file(file, kind=MediaKind.DOCUMENT, purpose=purpose, max_mb=max_mb)


def _lead_source(request):
    """Where a quote request came from: utm params, referrer and ?type= — stored on the lead."""
    parts = []
    utm = [f"{k[4:]}={request.GET[k][:40]}" for k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content") if request.GET.get(k)]
    if utm:
        parts.append("utm " + " ".join(utm))
    referer = request.META.get("HTTP_REFERER", "")
    if referer:
        ref = urlsplit(referer)
        own_host = urlsplit(settings.APP_URL).netloc
        if ref.netloc and ref.netloc not in (own_host, request.get_host()):
            parts.append(f"ref {ref.netloc}{ref.path}"[:120])
        elif ref.path and ref.path != request.path:
            parts.append(f"from {ref.path}"[:120])
    if request.GET.get("type"):
        parts.append(f"type {request.GET['type'][:60]}")
    return " · ".join(parts)[:200] or "direct"


def _project_type_from_query(value):
    value = (value or "").strip()
    if not value:
        return ""
    if value in c.SERVICE_BY_SLUG:
        return c.SERVICE_BY_SLUG[value]["project_type"]
    if value in c.SOLUTION_PAGE_BY_SLUG:
        return c.SOLUTION_PAGE_BY_SLUG[value]["project_type"]
    for pt in c.PROJECT_TYPES:
        if pt.lower() == value.lower():
            return pt
    return ""


# ─── Pages ──────────────────────────────────────────────────────────────────


def home(request):
    return page(
        request, "website/home.html",
        title=f"{BRAND} — High-Quality AI Data Annotation, Built for Scale",
        description=(
            "Reliable image, video, text and multimodal annotation services powered by skilled teams, structured "
            "workflows and dedicated quality control. Specialists in human action and video annotation."
        ),
        schema=[seo.organization(), seo.website(), seo.faq_page(c.HOME_FAQS)],
        services=c.SERVICES, industries=c.INDUSTRIES, faqs=c.HOME_FAQS, modalities=c.MODALITIES,
        specialization=c.SPECIALIZATION, segments=c.ACTION_SEGMENTS, cv_solutions=c.CV_SOLUTIONS,
        qa_steps=c.QA_STEPS, workflow=c.CLIENT_WORKFLOW, environments=c.ENVIRONMENTS, formats=c.DATA_FORMATS,
        security_items=c.SECURITY_ITEMS[:6], team_roles=c.TEAM_ROLES, annotation_types=c.ANNOTATION_TYPES,
        training=c.TRAINING_SYSTEM, statements=c,
    )


def services(request):
    description = (
        "Image, video, action & activity, action description, text and OCR / document annotation services — "
        "delivered by trained teams with layered review and QA."
    )
    return page(
        request, "website/services.html",
        title="AI Data Annotation Services", description=description,
        crumbs=[("Services", None)],
        schema=[seo.service("AI data annotation services", description, request.path, "Data annotation", [s["name"] for s in c.SERVICES])],
        services=c.SERVICES, qa_steps=c.QA_STEPS, workflow=c.CLIENT_WORKFLOW, statements=c, segments=c.ACTION_SEGMENTS,
    )


def service_detail(request, slug):
    svc = c.SERVICE_BY_SLUG.get(slug)
    if not svc:
        raise Http404("Unknown service")
    return page(
        request, "website/service_detail.html",
        title=svc["title"], description=svc["meta"],
        crumbs=[("Services", reverse("website:services")), (svc["name"], None)],
        schema=[
            seo.service(svc["h1"], svc["meta"], request.path, svc["name"], [i[0] for i in svc["includes"]]),
            seo.faq_page(svc["faqs"]),
        ],
        svc=svc, related=_services(svc["related"]), seo_pages=_solution_pages(svc.get("seo", [])),
        segments=c.ACTION_SEGMENTS, qa_steps=c.QA_STEPS, statements=c,
        faq_title=f"Questions about {svc['name_lc']}", cta_title=f"Start your {svc['name_lc']} project",
    )


def industries(request):
    description = (
        "Data annotation for retail, robotics, autonomous systems, healthcare, manufacturing, agriculture, security, "
        "sports and AI research — image, video and action labels for each use case."
    )
    return page(
        request, "website/industries.html",
        title="Industries We Support — Annotation by Use Case", description=description,
        crumbs=[("Industries", None)],
        schema=[seo.web_page("Industries", description, request.path, "CollectionPage")],
        industries=c.INDUSTRIES, services_by_slug=c.SERVICE_BY_SLUG,
    )


def solutions(request):
    description = (
        "Annotation for computer vision: object detection, image segmentation, pose / keypoint estimation, object "
        "tracking and action recognition. " + c.DATASET_STATEMENT
    )
    return page(
        request, "website/solutions.html",
        title="Annotation Solutions for Computer Vision", description=description,
        crumbs=[("Solutions", None)],
        schema=[seo.service("Computer vision annotation", description, request.path, "Data annotation", [s["name"] for s in c.CV_SOLUTIONS])],
        cv_solutions=c.CV_SOLUTIONS, solution_pages=c.SOLUTION_PAGES, statements=c,
        mosaic=[("detection", "object detection"), ("segmentation", "segmentation"), ("pose", "pose / keypoints"), ("tracking", "tracking")],
    )


def solution_detail(request, slug):
    sp = c.SOLUTION_PAGE_BY_SLUG.get(slug)
    if not sp:
        raise Http404("Unknown solution")
    return page(
        request, "website/solution_detail.html",
        title=sp["title"], description=sp["meta"],
        crumbs=[("Solutions", reverse("website:solutions")), (sp["name"], None)],
        schema=[seo.service(sp["h1"], sp["meta"], request.path, sp["name"], [d[0] for d in sp["deliver"]]), seo.faq_page(sp["faqs"])],
        sp=sp, related=_services(sp["related_services"]), related_pages=_solution_pages(sp["related_pages"]),
        segments=c.ACTION_SEGMENTS, workflow=c.CLIENT_WORKFLOW, statements=c,
    )


def capability(request):
    description = (
        "Built to scale with your dataset: skilled annotation workforce, dedicated project teams, team leads, "
        "reviewers and QA, and a structured training system. " + c.SCALE_STATEMENT
    )
    return page(
        request, "website/capability.html",
        title="Our Capability — Built to Scale With Your Dataset", description=description,
        crumbs=[("Our Capability", None)],
        schema=[seo.web_page("Our Capability", description, request.path, "AboutPage")],
        team_roles=c.TEAM_ROLES, training=c.TRAINING_SYSTEM, specialization=c.SPECIALIZATION,
        segments=c.ACTION_SEGMENTS, statements=c, pillars=c.CAPABILITY_PILLARS, scale_steps=c.SCALE_STEPS,
    )


def quality(request):
    description = (
        "Our quality assurance workflow: Annotation → Review → QA → Correction → Final Delivery, with checks for "
        "accuracy, consistency, boundaries, missing annotations and guideline compliance."
    )
    return page(
        request, "website/quality.html",
        title="Quality Assurance — Multi-Layer Annotation QA", description=description,
        crumbs=[("Quality Assurance", None)],
        schema=[seo.web_page("Quality Assurance", description, request.path), seo.faq_page(c.QUALITY_FAQS)],
        qa_steps=c.QA_STEPS, qa_checks=c.QA_CHECKS, training=c.TRAINING_SYSTEM, faqs=c.QUALITY_FAQS,
        loop_steps=c.FEEDBACK_LOOP, principles=c.QUALITY_PRINCIPLES,
    )


def platforms(request):
    description = (
        "Already have your own annotation server? Our team can adapt to your existing workflow — client servers, "
        "CVAT, Supervisely, Roboflow or custom platforms — and deliver in YOLO, COCO, Pascal VOC, JSON and more."
    )
    return page(
        request, "website/platforms.html",
        title="Platforms & Workflow — Work in Your Environment", description=description,
        crumbs=[("Company", None), ("Platforms & Workflow", None)],
        schema=[seo.web_page("Platforms & Workflow", description, request.path)],
        environments=c.ENVIRONMENTS, formats=c.DATA_FORMATS, workflow=c.CLIENT_WORKFLOW, statements=c,
    )


def security(request):
    description = (
        "How we protect client data: confidential project handling, controlled and project-specific access, "
        "role-based permissions, secure login, NDA support and a secure internal training environment."
    )
    return page(
        request, "website/security.html",
        title="Security & Confidentiality", description=description,
        crumbs=[("Company", None), ("Security & Confidentiality", None)],
        schema=[seo.web_page("Security & Confidentiality", description, request.path)],
        security_items=c.SECURITY_ITEMS, access_matrix=c.ACCESS_MATRIX,
    )


def about(request):
    description = (
        f"{BRAND} is an AI data annotation company: a skilled, remote annotation workforce with structured "
        "training, layered QA and experience across video, image and text annotation."
    )
    return page(
        request, "website/about.html",
        title=f"About {BRAND} — AI Data Annotation Company", description=description,
        crumbs=[("Company", None), ("About Us", None)],
        schema=[seo.web_page(f"About {BRAND}", description, request.path, "AboutPage"), seo.organization()],
        team_roles=c.TEAM_ROLES, statements=c, services=c.SERVICES, focus=c.ABOUT_FOCUS,
        principles=c.ABOUT_PRINCIPLES,
        about_lead=(
            f"{BRAND} provides image, video, text and multimodal annotation services. We focus on producing "
            "consistent, well-reviewed training data — and we've built our team, training and QA around it."
        ),
    )


def privacy(request):
    return page(
        request, "website/privacy.html",
        title="Privacy Policy", description=f"How {BRAND} collects, uses and protects personal information submitted through this website.",
        crumbs=[("Privacy Policy", None)],
    )


def terms(request):
    return page(
        request, "website/terms.html",
        title="Terms of Use", description=f"Terms governing the use of the {BRAND} website.",
        crumbs=[("Terms of Use", None)],
    )


# ─── Forms ──────────────────────────────────────────────────────────────────


def quote(request):
    if request.method == "POST":
        form = QuoteForm(request.POST, request.FILES)
        if _is_spam(form):
            return redirect("website:quote_thanks")
        if form.is_valid():
            if _rate_limited(request, "quote"):
                form.add_error(None, _rate_message())
                form.rate_limited = True
            else:
                d = form.cleaned_data
                try:
                    attachment = _store(d.get("attachment"), "quote", 15)
                except ValidationError as exc:
                    form.add_error("attachment", exc)
                else:
                    with transaction.atomic():
                        q = QuoteRequest.objects.create(
                            name=d["name"], company=d.get("company", ""), email=d["email"], phone=d.get("phone", ""),
                            project_type=d["project_type"], annotation_types=list(d.get("annotation_types") or []),
                            dataset_size=d.get("dataset_size", ""), timeline=d.get("timeline", ""),
                            platform=d.get("platform", ""), requirements=d.get("requirements", ""),
                            attachment=attachment, source=d.get("source") or "website", ip_address=_ip(request),
                        )
                        label = f"{q.name}{f' ({q.company})' if q.company else ''} · {q.project_type}"
                        notify_admins(f"New quote request: {label}", "quote_admin",
                                      {"quote": q, "review_url": _review_url("backoffice:lead_detail", q.pk)})
                        send_email(q.email, "We've received your request", "quote_confirmation", {"quote": q})
                    return redirect("website:quote_thanks")
    else:
        form = QuoteForm(initial={
            "project_type": _project_type_from_query(request.GET.get("type")),
            "source": _lead_source(request),
        })
    description = (
        "Request a quote for image, video, action, text or document annotation. Tell us about your dataset and "
        "we'll review your requirements and propose a pilot."
    )
    return page(
        request, "website/quote.html",
        title="Request a Quote — AI Data Annotation", description=description,
        crumbs=[("Request a Quote", None)],
        schema=[seo.web_page("Request a Quote", description, request.path, "ContactPage")],
        status=429 if getattr(form, "rate_limited", False) else 200,
        form=form, workflow=c.CLIENT_WORKFLOW, statements=c, next_steps=c.QUOTE_NEXT_STEPS, helpful=c.QUOTE_HELPFUL,
    )


def quote_thanks(request):
    return page(
        request, "website/quote_thanks.html",
        title="Thank you — request received", description="We've received your quote request.",
        crumbs=[("Request a Quote", reverse("website:quote")), ("Thank you", None)], noindex=True,
        workflow=c.CLIENT_WORKFLOW,
    )


def contact(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if _is_spam(form):
            return redirect("website:contact_thanks")
        if form.is_valid():
            if _rate_limited(request, "contact"):
                form.add_error(None, _rate_message())
                form.rate_limited = True
            else:
                d = form.cleaned_data
                with transaction.atomic():
                    m = ContactMessage.objects.create(
                        name=d["name"], email=d["email"], company=d.get("company", ""), phone=d.get("phone", ""),
                        subject=d.get("subject", ""), message=d["message"], ip_address=_ip(request),
                    )
                    notify_admins(f"New contact message: {m.subject or m.name}", "contact_admin",
                                  {"msg": m, "review_url": _review_url("backoffice:message_detail", m.pk)})
                    send_email(m.email, f"Thanks for contacting {BRAND}", "contact_confirmation", {"msg": m})
                return redirect("website:contact_thanks")
    else:
        form = ContactForm()
    description = f"Contact {BRAND} about AI data annotation projects, partnerships or general questions."
    return page(
        request, "website/contact.html",
        title=f"Contact {BRAND}", description=description,
        crumbs=[("Contact", None)],
        schema=[seo.web_page(f"Contact {BRAND}", description, request.path, "ContactPage")],
        status=429 if getattr(form, "rate_limited", False) else 200,
        form=form,
    )


def contact_thanks(request):
    return page(
        request, "website/contact_thanks.html",
        title="Thank you — message received", description="We've received your message.",
        crumbs=[("Contact", reverse("website:contact")), ("Thank you", None)], noindex=True,
    )


def careers(request):
    if request.method == "POST":
        form = ApplicationForm(request.POST, request.FILES)
        if _is_spam(form):
            return redirect("website:careers_thanks")
        if form.is_valid():
            if _rate_limited(request, "careers"):
                form.add_error(None, _rate_message())
                form.rate_limited = True
            else:
                d = form.cleaned_data
                cv = sample = None
                try:
                    cv = _store(d.get("cv"), "cv", 10)
                    sample = _store(d.get("sample"), "sample", 10)
                except ValidationError as exc:
                    if cv is not None:
                        delete_asset(cv)
                        form.add_error("sample", exc)
                    else:
                        form.add_error("cv", exc)
                else:
                    with transaction.atomic():
                        app = JobApplication.objects.create(
                            full_name=d["full_name"], email=d["email"], phone=d["phone"], location=d["location"],
                            experience=d.get("experience", ""), annotation_experience=d.get("annotation_experience", ""),
                            preferred_work_type=d.get("preferred_work_type", ""), availability=d.get("availability", ""),
                            skills=form.skills_list(), portfolio_url=d.get("portfolio_url", ""), cv=cv, sample=sample,
                            ip_address=_ip(request),
                        )
                        notify_admins(f"New job application: {app.full_name} · {app.location}", "application_admin",
                                      {"application": app, "review_url": _review_url("backoffice:applicant_detail", app.pk)})
                        send_email(app.email, "Application received", "application_confirmation", {"application": app})
                    return redirect("website:careers_thanks")
    else:
        form = ApplicationForm()
    description = (
        f"Join {BRAND} as an annotator, reviewer or QA member. Structured training, daily feedback and remote "
        "work on real AI data annotation projects."
    )
    return page(
        request, "website/careers.html",
        title="Careers — Join Our Annotation Team", description=description,
        crumbs=[("Company", None), ("Careers", None)],
        schema=[seo.web_page("Careers", description, request.path), seo.faq_page(c.CAREERS_FAQS)],
        status=429 if getattr(form, "rate_limited", False) else 200,
        form=form, roles=c.CAREER_ROLES, training=c.TRAINING_SYSTEM, faqs=c.CAREERS_FAQS,
        why_join=c.WHY_JOIN, training_steps=c.TRAINING_STEPS,
    )


def careers_thanks(request):
    return page(
        request, "website/careers_thanks.html",
        title="Application received", description="We've received your application.",
        crumbs=[("Careers", reverse("website:careers")), ("Application received", None)], noindex=True,
    )


# ─── robots.txt & sitemap.xml ───────────────────────────────────────────────


@require_GET
def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /portal/",
        "Disallow: /admin/",
        "Disallow: /client/",
        "Disallow: /django-admin/",
        "Disallow: /media/",
        "Disallow: /account/",
        "Disallow: /password/",
        "",
        f"Sitemap: {settings.APP_URL}{reverse('website:sitemap')}",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


class _AppSite:
    """Stand-in for django.contrib.sites: absolute sitemap URLs always use settings.APP_URL."""

    def __init__(self):
        parts = urlsplit(settings.APP_URL)
        self.protocol = parts.scheme or "https"
        self.domain = (parts.netloc + parts.path).rstrip("/")
        self.name = self.domain


@require_GET
def sitemap_xml(request):
    site = _AppSite()
    urls = []
    for sitemap in SITEMAPS.values():
        sm = sitemap() if isinstance(sitemap, type) else sitemap
        assert isinstance(sm, Sitemap)
        urls.extend(sm.get_urls(site=site, protocol=site.protocol))
    xml = render_to_string("sitemap.xml", {"urlset": urls})
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")
