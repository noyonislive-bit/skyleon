from django.contrib import admin
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "Skyloon AI — database admin"
admin.site.site_title = "Skyloon AI database admin"
admin.site.index_title = "Low-level data administration (super admins only)"

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url=static("img/favicon.svg"), permanent=True)),
    path("django-admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("media/", include("apps.storage.urls")),
    path("", include("apps.practice.urls")),  # /portal/practice/… and /admin/practice/…
    path("", include("apps.guides.urls")),  # /portal/guides/… and /admin/guides/…
    path("portal/", include("apps.portal.urls")),
    path("admin/", include("apps.backoffice.urls")),
    path("client/", include("apps.clients.urls")),
    path("", include("apps.website.urls")),
]

handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"
handler403 = "apps.core.views.error_403"
