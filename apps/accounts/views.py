from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core import ratelimit

from . import services
from .forms import LoginForm, SignupForm, StyledPasswordResetForm, StyledSetPasswordForm
from .models import Role, User, UserStatus

# Failed sign-ins are limited per (IP, account) and, more loosely, per IP — so one office behind a
# shared IP is not locked out by a single person, and guessing many accounts from one IP is still capped.
LOGIN_LIMIT, LOGIN_IP_LIMIT, LOGIN_WINDOW = 5, 30, 15 * 60


def _safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return fallback


def login_keys(request) -> tuple[str, str]:
    ip = ratelimit.client_ip(request)
    ident = str(request.POST.get("identifier") or "").strip().lower()[:150]
    return f"login:{ip}:{ident}", f"login-ip:{ip}"


def login_locked(request) -> bool:
    account_key, ip_key = login_keys(request)
    return ratelimit.is_limited(account_key, LOGIN_LIMIT) or ratelimit.is_limited(ip_key, LOGIN_IP_LIMIT)


def login_failed(request) -> None:
    account_key, ip_key = login_keys(request)
    ratelimit.hit(account_key, LOGIN_LIMIT, LOGIN_WINDOW)
    ratelimit.hit(ip_key, LOGIN_IP_LIMIT, LOGIN_WINDOW)


def login_view(request, portal="employee"):
    if request.user.is_authenticated:
        return redirect("accounts:after_login")
    template = "accounts/client_login.html" if portal == "client" else "accounts/login.html"
    if request.method == "POST" and login_locked(request):
        # Locked: the password is not checked at all (so the answer can't reveal whether it was right).
        login_failed(request)
        form = LoginForm(request, initial={"identifier": request.POST.get("identifier", "")})
        lockout = ("Too many sign-in attempts. Please wait 15 minutes and try again." if portal == "client"
                   else "অনেকবার ভুল চেষ্টা হয়েছে। ১৫ মিনিট পর আবার চেষ্টা করুন।")
        return render(request, template, {"form": form, "lockout": lockout, "next": request.POST.get("next", "")}, status=429)
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.user
            login(request, user)
            ratelimit.reset(login_keys(request)[0])
            if not form.cleaned_data.get("remember"):
                request.session.set_expiry(0)
            return redirect(_safe_next(request, reverse("accounts:after_login")))
        login_failed(request)
    return render(request, template, {"form": form, "next": request.GET.get("next", "")})


@login_required
def after_login(request):
    user = request.user
    if user.status == UserStatus.PENDING:
        return redirect("accounts:pending")
    return redirect(user.home_url())


@require_POST
def logout_view(request):
    is_client = getattr(request.user, "role", None) == Role.CLIENT
    logout(request)
    if is_client:
        messages.success(request, "You have been signed out.")
        return redirect("accounts:client_login")
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
    """Set-password page (password reset and account invitations). Bangla for employees; English for
    client accounts, whose portal and emails are in English."""

    template_name = "accounts/password_reset_confirm.html"
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")
    for_client = False

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        self.for_client = getattr(user, "role", None) == Role.CLIENT
        if self.for_client:
            translation.activate("en")
            self.request.LANGUAGE_CODE = "en"
        return user

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "for_client": self.for_client}

    def get_success_url(self):
        url = super().get_success_url()
        return f"{url}?for=client" if self.for_client else url


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"

    def get_context_data(self, **kwargs):
        for_client = self.request.GET.get("for") == "client"
        if for_client:
            translation.activate("en")
        return {**super().get_context_data(**kwargs), "for_client": for_client}
