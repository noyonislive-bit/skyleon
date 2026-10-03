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
