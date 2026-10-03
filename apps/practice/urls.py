from django.urls import path

from . import manage_views, views

app_name = "practice"

# Included at the site root (before the portal/admin includes) so the employee
# pages live under /portal/practice/ and management pages under /admin/practice/.
urlpatterns = [
    path("portal/practice/", views.task_list, name="list"),
    path("portal/practice/<int:pk>/", views.workspace, name="workspace"),
    path("portal/practice/<int:pk>/save/", views.save, name="save"),
    path("portal/practice/<int:pk>/submit/", views.submit, name="submit"),
    path("portal/practice/<int:pk>/task-error/", views.task_error, name="task_error"),
    path("portal/practice/results/<int:attempt_id>/", views.result, name="result"),
    path("admin/practice/", manage_views.manage_list, name="manage"),
    path("admin/practice/new/", manage_views.task_form, name="manage_new"),
    path("admin/practice/settings/", manage_views.tool_settings, name="manage_settings"),
    path("admin/practice/<int:pk>/edit/", manage_views.task_form, name="manage_edit"),
    path("admin/practice/<int:pk>/publish/", manage_views.publish, name="manage_publish"),
    path("admin/practice/<int:pk>/delete/", manage_views.delete, name="manage_delete"),
    path("admin/practice/<int:pk>/reference/", manage_views.reference_editor, name="manage_reference"),
    path("admin/practice/<int:pk>/reference/save/", manage_views.reference_save, name="manage_reference_save"),
    path("admin/practice/<int:pk>/results/", manage_views.results, name="manage_results"),
    path("admin/practice/attempts/<int:attempt_id>/", manage_views.attempt_detail, name="manage_attempt"),
]
