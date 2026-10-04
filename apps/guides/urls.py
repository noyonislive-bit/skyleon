from django.urls import path

from . import manage_views, views

app_name = "guides"

# Included at the site root (before the portal/admin includes): employee pages
# live under /portal/guides/, management pages under /admin/guides/.
urlpatterns = [
    # Employee reader
    path("portal/guides/", views.guide_list, name="list"),
    path("portal/guides/step/<int:pk>/done/", views.toggle_done, name="done"),
    path("portal/guides/<slug:slug>/", views.detail, name="detail"),
    path("portal/guides/<slug:slug>/step/<slug:anchor>/", views.step, name="step"),
    # Admin
    path("admin/guides/", manage_views.manage_list, name="manage"),
    path("admin/guides/new/", manage_views.guide_form, name="manage_new"),
    path("admin/guides/import/", manage_views.import_view, name="manage_import"),
    path("admin/guides/import-document/", manage_views.doc_import, name="manage_doc_import"),
    path("admin/guides/video-info/", manage_views.video_info, name="manage_video_info"),
    path("admin/guides/<int:pk>/", manage_views.guide_form, name="manage_edit"),
    path("admin/guides/<int:pk>/publish/", manage_views.publish, name="manage_publish"),
    path("admin/guides/<int:pk>/delete/", manage_views.delete, name="manage_delete"),
    path("admin/guides/<int:pk>/progress/", manage_views.progress, name="manage_progress"),
    path("admin/guides/<int:pk>/export/", manage_views.export, name="manage_export"),
    path("admin/guides/<int:pk>/sections/new/", manage_views.section_form, name="manage_section_new"),
    path("admin/guides/sections/<int:section_id>/edit/", manage_views.section_form, name="manage_section_edit"),
    path("admin/guides/sections/<int:section_id>/delete/", manage_views.section_delete, name="manage_section_delete"),
    path("admin/guides/sections/<int:section_id>/move/", manage_views.section_move, name="manage_section_move"),
    path("admin/guides/sections/<int:section_id>/steps/new/", manage_views.step_form, name="manage_step_new"),
    path("admin/guides/steps/<int:step_id>/edit/", manage_views.step_form, name="manage_step_edit"),
    path("admin/guides/steps/<int:step_id>/delete/", manage_views.step_delete, name="manage_step_delete"),
    path("admin/guides/steps/<int:step_id>/move/", manage_views.step_move, name="manage_step_move"),
    path("admin/guides/<int:pk>/task-errors/new/", manage_views.error_form, name="manage_error_new"),
    path("admin/guides/task-errors/<int:error_id>/edit/", manage_views.error_form, name="manage_error_edit"),
    path("admin/guides/task-errors/<int:error_id>/delete/", manage_views.error_delete, name="manage_error_delete"),
    path("admin/guides/task-errors/<int:error_id>/move/", manage_views.error_move, name="manage_error_move"),
    path("admin/guides/verify/<str:kind>/<int:obj_id>/", manage_views.verify, name="manage_verify"),
    path("admin/guides/<int:pk>/segments/", manage_views.segments, name="manage_segments"),
    path("admin/guides/<int:pk>/segments/save/", manage_views.segments_save, name="manage_segments_save"),
]
