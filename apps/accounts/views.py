from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core import ratelimit

from . import services
from .forms import LoginForm, SignupForm, StyledPasswordResetForm, StyledSetPasswordForm
from .models import Role, User, UserStatus

LOGIN_LIMIT, LOGIN_WINDOW = 10, 15 * 60


def _safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return fallback


def login_view(request, portal="employee"):
    if request.user.is_authenticated:
        return redirect("accounts:after_login")
    ip = ratelimit.client_ip(request)
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST":
        key = f"login:{ip}"
        if ratelimit.is_limited(key, LOGIN_LIMIT):
            form.add_error(None, "Too many sign-in attempts. Please wait 15 minutes and try again." if portal == "client"
                           else "অনেকবার ভুল চেষ্টা হয়েছে। ১৫ মিনিট পর আবার চেষ্টা করুন।")
        elif form.is_valid():
            user = form.user
            login(request, user)
            ratelimit.reset(key)
            if not form.cleaned_data.get("remember"):
                request.session.set_expiry(0)
            return redirect(_safe_next(request, reverse("accounts:after_login")))
        else:
            ratelimit.hit(key, LOGIN_LIMIT, LOGIN_WINDOW)
    template = "accounts/client_login.html" if portal == "client" else "accounts/login.html"
    return render(request, template, {"form": form, "next": request.GET.get("next", "")})


@login_required
def after_login(request):
    user = request.user
    if user.status == UserStatus.PENDING:
        return redirect("accounts:pending")
    return redirect(user.home_url())


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "আপনি লগআউট করেছেন।")
    return redirect("accounts:login")


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:after_login")
    form = SignupForm(request.POST or None)
    if request.method == "POST":
        if ratelimit.hit(f"signup:{ratelimit.client_ip(request)}", 5, 60 * 60):
            form.add_error(None, "আপনার নেটওয়ার্ক থেকে অনেকবার অ্যাকাউন্ট খোলার চেষ্টা হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন।")
        elif form.is_valid():
            d = form.cleaned_data
            user = User.objects.create_user(
                email=d["email"], password=d["password1"], name=d["name"], phone=d.get("phone") or "",
                location=d.get("location") or "", role=Role.EMPLOYEE, status=UserStatus.PENDING,
            )
            services.notify_new_signup(user)
            login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
            return redirect("accounts:pending")
    return render(request, "accounts/signup.html", {"form": form})


@login_required
def pending_view(request):
    if request.user.status != UserStatus.PENDING:
        return redirect("accounts:after_login")
    return render(request, "accounts/pending.html")


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = StyledPasswordResetForm
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"
    subject_template_name = "emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        if ratelimit.hit(f"pwreset:{ratelimit.client_ip(self.request)}", 5, 60 * 60):
            form.add_error(None, "অনেকবার রিসেটের অনুরোধ এসেছে। কিছুক্ষণ পর আবার চেষ্টা করুন।")
            return self.form_invalid(form)
        self.extra_email_context = {"APP_URL": settings.APP_URL}
        return super().form_valid(form)


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
