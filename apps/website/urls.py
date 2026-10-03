# NOTE: temporary stubs — the public website implementation replaces these views.
from django.urls import path

from apps.core.views import health

from . import views

app_name = "website"

urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.stub, name="services"),
    path("services/<slug:slug>/", views.stub, name="service_detail"),
    path("industries/", views.stub, name="industries"),
    path("solutions/", views.stub, name="solutions"),
    path("solutions/<slug:slug>/", views.stub, name="solution_detail"),
    path("capability/", views.stub, name="capability"),
    path("quality-assurance/", views.stub, name="quality"),
    path("platforms-and-workflow/", views.stub, name="platforms"),
    path("security/", views.stub, name="security"),
    path("about/", views.stub, name="about"),
    path("careers/", views.stub, name="careers"),
    path("careers/thank-you/", views.stub, name="careers_thanks"),
    path("contact/", views.stub, name="contact"),
    path("contact/thank-you/", views.stub, name="contact_thanks"),
    path("request-a-quote/", views.stub, name="quote"),
    path("request-a-quote/thank-you/", views.stub, name="quote_thanks"),
    path("privacy/", views.stub, name="privacy"),
    path("terms/", views.stub, name="terms"),
    path("healthz/", health, name="health"),
]
