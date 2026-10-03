from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrEmployeeIdBackend(ModelBackend):
    """Log in with either an email address or an employee ID (e.g. SKY-0042)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = (username or kwargs.get("email") or "").strip()
        if not identifier or not password:
            return None
        try:
            if "@" in identifier:
                user = User.objects.get(email__iexact=identifier)
            else:
                user = User.objects.get(employee_id__iexact=identifier)
        except User.DoesNotExist:
            User().set_password(password)  # equalise timing
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
