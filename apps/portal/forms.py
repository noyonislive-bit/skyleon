from django.contrib.auth.forms import PasswordChangeForm

from apps.accounts.forms import ProfileForm
from apps.core.forms import StyledFormMixin


class PortalProfileForm(ProfileForm):
    """The shared profile form with Bangla labels for the employee portal."""

    LABELS = {
        "name": "নাম",
        "title": "পদবি",
        "phone": "ফোন নম্বর",
        "location": "এলাকা / শহর",
        "skills_text": "দক্ষতা",
        "bio": "নিজের সম্পর্কে",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, label in self.LABELS.items():
            if name in self.fields:
                self.fields[name].label = label
        self.fields["skills_text"].help_text = "কমা দিয়ে আলাদা করে লিখুন, যেমন: CVAT, polygon, video segmentation"


class PortalPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.pop("autofocus", None)
        self.fields["old_password"].label = "বর্তমান পাসওয়ার্ড"
        self.fields["new_password1"].label = "নতুন পাসওয়ার্ড"
        self.fields["new_password1"].help_text = "কমপক্ষে 8 অক্ষর। খুব প্রচলিত বা শুধু সংখ্যার পাসওয়ার্ড দেবেন না।"
        self.fields["new_password2"].label = "নতুন পাসওয়ার্ড আবার লিখুন"
        self.fields["new_password2"].help_text = "মিলিয়ে দেখতে একই পাসওয়ার্ড আরেকবার লিখুন।"
