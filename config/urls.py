from django.contrib import admin
from django.templatetags.static import static
from django.urls import include, path, reverse
from django.utils.http import urlencode
from django.views.generic import RedirectView


class FaviconView(RedirectView):
    """Resolved per request: static() needs the collectstatic manifest, which may not exist yet
    when management commands such as `migrate` import the URLconf on a fresh install."""
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return static("img/favicon.svg")


class DjangoAdminLoginView(RedirectView):
    """/django-admin/ signs in through the site's own (rate-limited) login page."""
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        nxt = self.request.GET.get("next") or "/django-admin/"
        return reverse("accounts:login") + "?" + urlencode({"next": nxt})

admin.site.site_header = "Skyloon AI — database admin"
admin.site.site_title = "Skyloon AI database admin"
admin.site.index_title = "Low-level data administration (super admins only)"

urlpatterns = [
    path("favicon.ico", FaviconView.as_view()),
    path("django-admin/login/", DjangoAdminLoginView.as_view()),
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

handler400 = "apps.core.views.error_400"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"
handler403 = "apps.core.views.error_403"
