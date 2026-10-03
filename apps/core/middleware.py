from django.utils import translation

# Paths whose pages are read by employees → Bangla. Everything else (public website,
# admin panel, client portal) stays English.
BANGLA_PREFIXES = ("/portal/", "/login/", "/signup/", "/account/", "/password/")


def is_bangla_path(path: str) -> bool:
    return path.startswith(BANGLA_PREFIXES)


class AreaLanguageMiddleware:
    """Activates Bangla for employee-facing areas so Django's own texts (form errors, dates) match."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = "bn" if is_bangla_path(request.path) else "en"
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        response.headers.setdefault("Content-Language", lang)
        return response


class SecurityHeadersMiddleware:
    """Adds headers Django does not set by default."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.path.startswith(("/portal", "/admin", "/client", "/django-admin")):
            # Private areas must never be cached by shared proxies.
            response.headers.setdefault("Cache-Control", "private, no-store")
        return response
