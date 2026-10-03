from django.urls import path

from . import views

app_name = "portal"

# URL names `dashboard`, `project_detail`, `tutorial_detail`, `feedback_detail` and `test_detail`
# (and their paths) are referenced by emails / notifications — keep them stable.
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Onboarding
    path("onboarding/", views.onboarding, name="onboarding"),
    path("onboarding/steps/<int:pk>/complete/", views.complete_step, name="onboarding_complete_step"),
    # Projects & guidelines
    path("projects/", views.project_list, name="projects"),
    path("projects/<slug:slug>/", views.project_detail, name="project_detail"),
    path("projects/<slug:slug>/guidelines/<int:pk>/", views.guideline_detail, name="guideline_detail"),
    path("projects/<slug:slug>/guidelines/<int:pk>/acknowledge/", views.guideline_ack, name="guideline_ack"),
    # Training
    path("training/", views.training, name="training"),
    path("training/<int:pk>/", views.tutorial_detail, name="tutorial_detail"),
    path("training/<int:pk>/complete/", views.tutorial_complete, name="tutorial_complete"),
    # Feedback
    path("feedback/", views.feedback_list, name="feedback"),
    path("feedback/<int:number>/", views.feedback_detail, name="feedback_detail"),
    path("feedback/<int:number>/acknowledge/", views.feedback_ack, name="feedback_ack"),
    # Tests
    path("tests/", views.test_list, name="tests"),
    path("tests/<int:pk>/", views.test_detail, name="test_detail"),
    path("tests/<int:pk>/start/", views.test_start, name="test_start"),
    path("tests/attempt/<int:attempt_id>/", views.test_take, name="test_take"),
    path("results/", views.results, name="results"),
    path("results/<int:attempt_id>/", views.result_detail, name="result_detail"),
    # Announcements, meetings, notifications
    path("announcements/", views.announcements, name="announcements"),
    path("announcements/read-all/", views.announcements_read_all, name="announcements_read_all"),
    path("announcements/<int:pk>/", views.announcement_detail, name="announcement_detail"),
    path("meetings/", views.meetings, name="meetings"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/menu/", views.notifications_menu, name="notifications_menu"),
    path("notifications/read-all/", views.notifications_read_all, name="notifications_read_all"),
    path("notifications/<int:pk>/open/", views.notification_open, name="notification_open"),
    # Profile
    path("profile/", views.profile, name="profile"),
    path("profile/history/", views.history, name="history"),
    # JSON endpoints (tracked player, mark-read)
    path("api/tutorials/<int:pk>/progress/", views.tutorial_heartbeat, name="tutorial_heartbeat"),
    path("api/feedback/<int:number>/progress/", views.feedback_heartbeat, name="feedback_heartbeat"),
    path("api/announcements/<int:pk>/read/", views.announcement_read, name="announcement_read"),
]
