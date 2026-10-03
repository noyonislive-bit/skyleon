"""
python manage.py import_guide path/to/guide.json [--replace] [--publish] [--dry-run]

Creates or updates a work guide (matched by "slug") from a JSON file.
See docs/GUIDES.md for the format and how video links are handled.
"""

import argparse
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, DjangoHelpFormatter

from apps.guides.importer import SCHEMA_HELP, GuideImportError, import_guide, load_json


class _Formatter(DjangoHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


class Command(BaseCommand):
    help = (
        "Create or update a work guide from a JSON file (matched by slug).\n\n"
        "  --replace   rebuild the sections/steps of an existing guide; steps whose anchors\n"
        "              still exist are updated in place, so employees keep their progress on them\n"
        "  --publish   publish the guide (otherwise new guides stay in draft)\n"
        "  --dry-run   validate only, save nothing\n\n"
        "Example: python manage.py import_guide apps/guides/fixtures/sample_guide.json --publish\n\n"
        + SCHEMA_HELP
        + "\nVideo links are embedded from their ORIGINAL source — nothing is downloaded or re-hosted."
    )

    def create_parser(self, prog_name, subcommand, **kwargs):
        kwargs["formatter_class"] = _Formatter
        return super().create_parser(prog_name, subcommand, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the guide JSON file (UTF-8)")
        parser.add_argument("--replace", action="store_true", help="Rebuild sections/steps of an existing guide")
        parser.add_argument("--publish", action="store_true", help="Publish the guide after importing")
        parser.add_argument("--dry-run", action="store_true", help="Validate only; nothing is saved")

    def handle(self, *args, path, replace, publish, dry_run, **options):
        file = Path(path)
        if not file.is_file():
            raise CommandError(f"File not found: {path}")
        try:
            data = load_json(file.read_bytes())
            result = import_guide(data, replace=replace, publish=publish, dry_run=dry_run)
        except GuideImportError as e:
            lines = "\n".join(f"  • {msg}" for msg in e.errors)
            raise CommandError(f"The guide was not imported ({len(e.errors)} problem{'s' if len(e.errors) != 1 else ''}):\n{lines}")
        for w in result.warnings:
            self.stdout.write(self.style.WARNING(f"warning: {w}"))
        g = result.guide
        verb = "Validated" if dry_run else ("Created" if result.created else "Updated")
        self.stdout.write(self.style.SUCCESS(
            f"{verb} guide “{g.title}” (slug: {g.slug}, status: {g.status}): "
            f"{result.sections} sections, {result.steps} steps."
        ))
        if not result.created:
            self.stdout.write(f"  kept {result.steps_kept} existing steps ({result.progress_kept} progress records), "
                              f"removed {result.steps_removed}.")
        if dry_run:
            self.stdout.write("  Dry run — nothing was saved.")
        else:
            self.stdout.write(f"  Employees: /portal/guides/{g.slug}/  ·  Admin: /admin/guides/{g.pk}/")
