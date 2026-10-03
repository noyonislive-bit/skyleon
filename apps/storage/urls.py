from django.urls import path

from . import views

app_name = "storage"

urlpatterns = [
    path("uploads/init/", views.upload_init, name="upload_init"),
    path("uploads/<uuid:asset_id>/chunk/", views.upload_chunk, name="upload_chunk"),
    path("uploads/<uuid:asset_id>/complete/", views.upload_complete, name="upload_complete"),
    path("external/", views.external_create, name="external_create"),
    path("<uuid:asset_id>/info/", views.asset_info, name="asset_info"),
    path("<uuid:asset_id>/preview/", views.preview, name="preview"),
    path("<uuid:asset_id>/stream/", views.stream, name="stream"),
]
