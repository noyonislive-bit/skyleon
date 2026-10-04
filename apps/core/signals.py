"""
Previews (GitHub Codespaces, Claude cloud sessions) keep their sample data complete by themselves:
after every `migrate` — which the preview runs on start and after each automatic update — a newer
sample set (seed_demo.SAMPLE_VERSION) is added on top of what is there. Live sites never do this
(DEBUG off, SAMPLE_DATA_AUTO off); there sample data is only added with `manage.py seed_demo`.
"""

import sys

from django.conf import settings
from django.core.management import call_command


def top_up_sample_data(sender, using="default", **kwargs):
    if not (settings.DEBUG and getattr(settings, "SAMPLE_DATA_AUTO", False)) or using != "default":
        return
    try:
        from apps.core.management.commands.seed_demo import REMOVED_KEY, SAMPLE_VERSION, VERSION_KEY, marker

        if marker(REMOVED_KEY) or marker(VERSION_KEY) >= SAMPLE_VERSION:
            return
        print("  Adding the latest sample data (preview only) …", file=sys.stderr)
        call_command("createcachetable", verbosity=0)
        call_command("seed_demo", if_outdated=True)
    except Exception as exc:  # a preview convenience must never break migrate
        print(f"  Sample data could not be added automatically ({exc}). Run: python manage.py seed_demo", file=sys.stderr)
