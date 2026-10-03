import re

from django.db import migrations

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def sanitize(apps, schema_editor):
    """Project colours are written into inline styles; anything that isn't a #rrggbb value becomes the brand green."""
    Project = apps.get_model("projects", "Project")
    for p in Project.objects.only("pk", "color"):
        if not HEX.match(p.color or ""):
            Project.objects.filter(pk=p.pk).update(color="#088650")


class Migration(migrations.Migration):
    dependencies = [("projects", "0002_green_theme_color")]
    operations = [migrations.RunPython(sanitize, migrations.RunPython.noop)]
