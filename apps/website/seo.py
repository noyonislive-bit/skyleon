"""
SEO helpers: page meta and JSON-LD structured data.

Views build a list of schema.org objects and pass `jsonld=ld(...)` to the
template; `website/base_site.html` prints it inside the `structured_data` block.
"""

import json

from django.conf import settings
from django.templatetags.static import static
from django.utils.safestring import mark_safe

from apps.core import site_settings

# Same escapes Django's json_script uses, so user/content strings can't close the <script>.
_JSON_ESCAPES = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}


def abs_url(path: str) -> str:
    if path.startswith("http"):
        return path
    return f"{settings.APP_URL}{path}"


def org_id() -> str:
    return f"{settings.APP_URL}/#organization"


def ld(*objects) -> str:
    """Render schema.org objects as <script type="application/ld+json"> tags."""
    tags = []
    for obj in objects:
        if not obj:
            continue
        data = {"@context": "https://schema.org", **obj}
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).translate(_JSON_ESCAPES)
        tags.append(f'<script type="application/ld+json">{payload}</script>')
    return mark_safe("\n".join(tags))


def organization() -> dict:
    brand = site_settings.BRAND
    company = site_settings.company()
    data = {
        "@type": "Organization",
        "@id": org_id(),
        "name": brand["name"],
        "legalName": brand["legal_name"],
        "url": f"{settings.APP_URL}/",
        "logo": abs_url(static("img/logo-512.png")),
        "image": abs_url(static("img/og-image.png")),
        "description": brand["description"],
    }
    if company.get("email"):
        data["email"] = company["email"]
        data["contactPoint"] = [{"@type": "ContactPoint", "contactType": "sales", "email": company["email"]}]
        if company.get("phone"):
            data["contactPoint"][0]["telephone"] = company["phone"]
    if company.get("phone"):
        data["telephone"] = company["phone"]
    if company.get("address"):
        data["address"] = {"@type": "PostalAddress", "streetAddress": company["address"]}
    same_as = [company.get(k) for k in ("linkedin", "facebook", "x", "youtube") if company.get(k)]
    if same_as:
        data["sameAs"] = same_as
    return data


def website() -> dict:
    return {
        "@type": "WebSite",
        "@id": f"{settings.APP_URL}/#website",
        "url": f"{settings.APP_URL}/",
        "name": site_settings.BRAND["name"],
        "description": site_settings.BRAND["description"],
        "publisher": {"@id": org_id()},
        "inLanguage": "en",
    }


def breadcrumb_list(crumbs, current_path: str) -> dict | None:
    """crumbs: [(label, url_or_None), …] without Home; the last item is the current page."""
    if not crumbs:
        return None
    items = [("Home", "/")] + [(label, url or current_path) for label, url in crumbs]
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": label, "item": abs_url(url)}
            for i, (label, url) in enumerate(items, start=1)
        ],
    }


def faq_page(faqs) -> dict | None:
    if not faqs:
        return None
    return {
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs
        ],
    }


def service(name: str, description: str, path: str, service_type: str | None = None, items=None) -> dict:
    data = {
        "@type": "Service",
        "name": name,
        "serviceType": service_type or name,
        "description": description,
        "url": abs_url(path),
        "provider": {"@type": "Organization", "@id": org_id(), "name": site_settings.BRAND["name"], "url": f"{settings.APP_URL}/"},
    }
    if items:
        data["hasOfferCatalog"] = {
            "@type": "OfferCatalog",
            "name": name,
            "itemListElement": [{"@type": "Offer", "itemOffered": {"@type": "Service", "name": i}} for i in items],
        }
    return data


def web_page(name: str, description: str, path: str, page_type: str = "WebPage") -> dict:
    return {
        "@type": page_type,
        "name": name,
        "description": description,
        "url": abs_url(path),
        "isPartOf": {"@id": f"{settings.APP_URL}/#website"},
        "about": {"@id": org_id()},
    }
