from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("projects/<slug:slug>/", views.placeholder, name="project_detail"),
    path("training/<int:pk>/", views.placeholder, name="tutorial_detail"),
    path("feedback/<int:number>/", views.placeholder, name="feedback_detail"),
    path("tests/<int:pk>/", views.placeholder, name="test_detail"),
]
