from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import redirect


class AccountStatusMiddleware:
    """Signs out users who were suspended while logged in."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.status == "suspended":
            logout(request)
            messages.error(request, "Your account has been suspended. Please contact your manager.")
            return redirect("accounts:login")
        return self.get_response(request)
