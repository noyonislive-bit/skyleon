from django.contrib.staticfiles.apps import StaticFilesConfig


class SkyleonStaticFilesConfig(StaticFilesConfig):
    """Skip build-only sources (Tailwind input CSS) when collecting static files."""

    ignore_patterns = [*StaticFilesConfig.ignore_patterns, "src", "*.map"]
