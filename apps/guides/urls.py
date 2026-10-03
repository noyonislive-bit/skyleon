from django.urls import path

from . import views

app_name = "guides"

# Included at the site root: employee pages under /portal/guides/, management under /admin/guides/.
urlpatterns = [
    path("portal/guides/", views.guide_list, name="list"),
    path("admin/guides/", views.manage_list, name="manage"),
]
