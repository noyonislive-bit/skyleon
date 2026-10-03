from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Skyleon — database admin"
admin.site.site_title = "Skyleon database admin"
admin.site.index_title = "Low-level data administration (super admins only)"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("media/", include("apps.storage.urls")),
    path("portal/", include("apps.portal.urls")),
    path("admin/", include("apps.backoffice.urls")),
    path("client/", include("apps.clients.urls")),
    path("", include("apps.website.urls")),
]

handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"
handler403 = "apps.core.views.error_403"
