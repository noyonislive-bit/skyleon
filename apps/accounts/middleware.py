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
            messages.error(request, "আপনার অ্যাকাউন্টটি স্থগিত (suspended) করা হয়েছে। আপনার ম্যানেজারের সাথে যোগাযোগ করুন।")
            return redirect("accounts:login")
        return self.get_response(request)
