"""Sitemaps for the public website (rendered by views.sitemap_xml with APP_URL as the domain)."""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from . import content

# url name → (priority, changefreq)
STATIC_PAGES = {
    "home": (1.0, "weekly"),
    "services": (0.9, "monthly"),
    "solutions": (0.9, "monthly"),
    "quote": (0.9, "monthly"),
    "industries": (0.8, "monthly"),
    "capability": (0.8, "monthly"),
    "quality": (0.8, "monthly"),
    "platforms": (0.7, "monthly"),
    "security": (0.7, "monthly"),
    "about": (0.7, "monthly"),
    "careers": (0.7, "weekly"),
    "contact": (0.7, "yearly"),
    "privacy": (0.2, "yearly"),
    "terms": (0.2, "yearly"),
}


class StaticPagesSitemap(Sitemap):
    def items(self):
        return list(STATIC_PAGES)

    def location(self, item):
        return reverse(f"website:{item}")

    def priority(self, item):
        return STATIC_PAGES[item][0]

    def changefreq(self, item):
        return STATIC_PAGES[item][1]


class ServicesSitemap(Sitemap):
    priority = 0.9
    changefreq = "monthly"

    def items(self):
        return [s["slug"] for s in content.SERVICES]

    def location(self, item):
        return reverse("website:service_detail", args=[item])


class SolutionPagesSitemap(Sitemap):
    priority = 0.8
    changefreq = "monthly"

    def items(self):
        return [p["slug"] for p in content.SOLUTION_PAGES]

    def location(self, item):
        return reverse("website:solution_detail", args=[item])


SITEMAPS = {
    "pages": StaticPagesSitemap,
    "services": ServicesSitemap,
    "solutions": SolutionPagesSitemap,
}
