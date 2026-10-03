from django import forms


class StyledFormMixin:
    """Adds the design-system CSS classes to every widget so templates stay clean."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            w = field.widget
            css = w.attrs.get("class", "")
            if isinstance(w, (forms.CheckboxInput,)):
                base = "checkbox"
            elif isinstance(w, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                base = "choice-list"
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                base = "select"
            elif isinstance(w, forms.Textarea):
                base = "textarea"
                w.attrs.setdefault("rows", 4)
            elif isinstance(w, forms.ClearableFileInput) or isinstance(w, forms.FileInput):
                base = "file-input"
            else:
                base = "input"
            w.attrs["class"] = f"{base} {css}".strip()
            if field.required and not isinstance(w, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                w.attrs.setdefault("required", True)


class HoneypotMixin(forms.Form):
    """Invisible field that bots fill in. Rendered by {% include "components/honeypot.html" %}."""

    website_url = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def clean_website_url(self):
        if self.cleaned_data.get("website_url"):
            raise forms.ValidationError("Spam detected.")
        return ""
