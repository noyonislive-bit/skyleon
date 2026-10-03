from django.contrib.auth.forms import PasswordChangeForm

from apps.core.forms import StyledFormMixin


class PortalPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.pop("autofocus", None)
        self.fields["new_password1"].help_text = "At least 8 characters. Avoid common or all-numeric passwords."
