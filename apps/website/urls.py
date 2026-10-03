from django.urls import path

from apps.core.views import health

from . import views

app_name = "website"

urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services, name="services"),
    path("services/<slug:slug>/", views.service_detail, name="service_detail"),
    path("industries/", views.industries, name="industries"),
    path("solutions/", views.solutions, name="solutions"),
    path("solutions/<slug:slug>/", views.solution_detail, name="solution_detail"),
    path("capability/", views.capability, name="capability"),
    path("quality-assurance/", views.quality, name="quality"),
    path("platforms-and-workflow/", views.platforms, name="platforms"),
    path("security/", views.security, name="security"),
    path("about/", views.about, name="about"),
    path("careers/", views.careers, name="careers"),
    path("careers/thank-you/", views.careers_thanks, name="careers_thanks"),
    path("contact/", views.contact, name="contact"),
    path("contact/thank-you/", views.contact_thanks, name="contact_thanks"),
    path("request-a-quote/", views.quote, name="quote"),
    path("request-a-quote/thank-you/", views.quote_thanks, name="quote_thanks"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
    path("healthz/", health, name="health"),
]
