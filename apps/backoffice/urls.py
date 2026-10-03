# NOTE: temporary stubs — the admin panel implementation replaces these views.
# The URL *names* below are a contract used by other areas (emails, website).
from django.urls import path

from . import views

app_name = "backoffice"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("employees/<int:pk>/", views.placeholder, name="employee_detail"),
    path("applicants/<int:pk>/", views.placeholder, name="applicant_detail"),
    path("leads/<int:pk>/", views.placeholder, name="lead_detail"),
    path("messages/<int:pk>/", views.placeholder, name="message_detail"),
]
