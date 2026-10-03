from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.template.loader import render_to_string
from django.utils import translation

from apps.core.forms import HoneypotMixin, StyledFormMixin

from .models import Role, User, UserStatus


def is_bn() -> bool:
    return (translation.get_language() or "").startswith("bn")


class LoginForm(StyledFormMixin, forms.Form):
    identifier = forms.CharField(
        label="Email or Employee ID", max_length=254,
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True, "placeholder": "you@company.com or SKY-0001"}),
    )
    password = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    remember = forms.BooleanField(label="Keep me signed in", required=False, initial=True)

    error_messages = {
        "invalid": "Incorrect email/employee ID or password.",
        "suspended": "This account has been suspended. Please contact your manager.",
    }

    error_messages_bn = {
        "invalid": "ইমেইল/এমপ্লয়ি আইডি অথবা পাসওয়ার্ড ভুল হয়েছে। আবার চেষ্টা করুন।",
        "suspended": "আপনার অ্যাকাউন্টটি স্থগিত (suspended) করা আছে। আপনার ম্যানেজারের সাথে যোগাযোগ করুন।",
    }

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)
        if is_bn():
            self.error_messages = self.error_messages_bn
            self.fields["identifier"].label = "ইমেইল বা এমপ্লয়ি আইডি"
            self.fields["identifier"].widget.attrs["placeholder"] = "you@company.com অথবা SKY-0001"
            self.fields["password"].label = "পাসওয়ার্ড"
            self.fields["remember"].label = "আমাকে লগইন রাখুন"

    def clean(self):
        data = super().clean()
        identifier, password = data.get("identifier"), data.get("password")
        if identifier and password:
            self.user = authenticate(self.request, username=identifier, password=password)
            if self.user is None:
                candidate = (
                    User.objects.filter(email__iexact=identifier).first()
                    if "@" in identifier
                    else User.objects.filter(employee_id__iexact=identifier).first()
                )
                if candidate and candidate.status == UserStatus.SUSPENDED and candidate.check_password(password):
                    raise forms.ValidationError(self.error_messages["suspended"])
                raise forms.ValidationError(self.error_messages["invalid"])
        return data


class SignupForm(StyledFormMixin, HoneypotMixin, forms.Form):
    name = forms.CharField(label="Full name", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    phone = forms.CharField(label="Phone", max_length=40, required=False, widget=forms.TextInput(attrs={"autocomplete": "tel"}))
    location = forms.CharField(label="City / country", max_length=120, required=False)
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text="At least 8 characters. Avoid common or all-numeric passwords.")
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    agree = forms.BooleanField(label="I agree to keep all project data and training material confidential.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if is_bn():
            labels = {
                "name": "পুরো নাম", "email": "ইমেইল", "phone": "ফোন নম্বর", "location": "শহর / দেশ",
                "password1": "পাসওয়ার্ড", "password2": "পাসওয়ার্ড আবার লিখুন",
                "agree": "আমি প্রজেক্টের সব ডেটা আর ট্রেনিং ম্যাটেরিয়াল গোপন রাখব।",
            }
            for name, label in labels.items():
                self.fields[name].label = label
            self.fields["password1"].help_text = "কমপক্ষে ৮ অক্ষর। খুব সাধারণ বা শুধু সংখ্যার পাসওয়ার্ড দেবেন না।"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "এই ইমেইলে আগেই একটা অ্যাকাউন্ট আছে। লগইন করুন, অথবা পাসওয়ার্ড ভুলে গেলে রিসেট করুন।" if is_bn()
                else "An account with this email already exists. Try signing in or resetting your password."
            )
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "দুইবার লেখা পাসওয়ার্ড মিলছে না।" if is_bn() else "The two passwords do not match.")
        if p1:
            try:
                password_validation.validate_password(p1, User(email=data.get("email", ""), name=data.get("name", "")))
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data


class StyledPasswordResetForm(StyledFormMixin, PasswordResetForm):
    """Django's reset form, but:
      * also for invited users who never set a password (Django skips accounts without a usable password),
      * the email goes through our outbox (Email log, retries) instead of being sent directly."""

    def get_users(self, email):
        return User.objects.filter(email__iexact=email, is_active=True)

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
        from apps.comms.services import queue_email
        from apps.core.site_settings import BRAND

        user = context.get("user")
        if getattr(user, "role", None) == Role.CLIENT:  # the client portal is in English
            queue_email(to_email, f"Password reset — {BRAND['name']}", "password_reset_en", context)
            return
        subject = "".join(render_to_string(subject_template_name, {**context, "brand": BRAND}).splitlines())
        queue_email(to_email, subject, "password_reset", context)


class StyledSetPasswordForm(StyledFormMixin, SetPasswordForm):
    pass


class ProfileForm(StyledFormMixin, forms.ModelForm):
    skills_text = forms.CharField(label="Skills", required=False, help_text="Comma separated, e.g. CVAT, polygon, video segmentation")

    class Meta:
        model = User
        fields = ["name", "phone", "location", "title", "bio"]
        widgets = {"bio": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["skills_text"].initial = ", ".join(self.instance.skills or [])

    def save(self, commit=True):
        user = super().save(commit=False)
        user.skills = [s.strip() for s in self.cleaned_data.get("skills_text", "").split(",") if s.strip()][:30]
        if commit:
            user.save()
        return user
