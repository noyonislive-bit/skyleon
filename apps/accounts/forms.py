from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm

from apps.core.forms import HoneypotMixin, StyledFormMixin

from .models import User, UserStatus


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

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

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

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Try signing in or resetting your password.")
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        if p1:
            try:
                password_validation.validate_password(p1, User(email=data.get("email", ""), name=data.get("name", "")))
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data


class StyledPasswordResetForm(StyledFormMixin, PasswordResetForm):
    pass


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
