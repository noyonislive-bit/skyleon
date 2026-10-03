"""
Access helpers for function-based and class-based views.

    @permission_required_code("content.manage")
    def view(request): ...

    class MyView(PermissionRequiredMixin, View):
        permission_code = "employees.manage"
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .models import UserStatus
from .permissions import has_permission


def _deny(request, code):
    user = request.user
    if not user.is_authenticated:
        if request.path.startswith("/client/"):
            return redirect_to_login(request.get_full_path(), login_url=reverse("accounts:client_login"))
        return redirect_to_login(request.get_full_path())
    if user.status == UserStatus.PENDING:
        return redirect("accounts:pending")
    raise PermissionDenied(f"Missing permission: {code}")


def permission_required_code(code: str):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not has_permission(request.user, code):
                return _deny(request, code)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


staff_required = permission_required_code("backoffice.access")
employee_required = permission_required_code("portal.access")


class PermissionRequiredMixin:
    permission_code: str = ""

    def dispatch(self, request, *args, **kwargs):
        if not has_permission(request.user, self.permission_code):
            return _deny(request, self.permission_code)
        return super().dispatch(request, *args, **kwargs)
