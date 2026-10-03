"""
Import a guide from JSON (see docs/GUIDES.md and `manage.py import_guide --help`).

    result = import_guide(data, replace=False, publish=False, user=None)

Validation collects every problem first and reports them together, with a path
such as `sections[2].steps[1].video_url`. The import runs in one transaction.
With `replace=True` an existing guide's sections/steps are rebuilt; steps whose
anchors still exist are updated in place, so employees' progress on them is kept.
A step / Task Error example keeps its "verified against the original" mark only
when its content is unchanged.
"""

import json
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.core.choices import ContentStatus
from apps.core.icons import ICONS

from . import services
from .models import Guide, GuideAccent, GuideKind, GuideSection, GuideStep, GuideTaskError
from .video import clean_url, parse_start

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

TOP_KEYS = {"slug", "title", "title_en", "summary", "kind", "icon", "accent", "source_url", "project_code", "order", "sections", "task_errors"}
SECTION_KEYS = {"title", "title_en", "anchor", "intro", "steps"}
STEP_KEYS = {"title", "anchor", "body", "body_en", "video_url", "video_caption", "video_start", "video_end", "actions",
             "estimated_minutes", "source_ref", "task_errors"}
ERROR_KEYS = {"title", "anchor", "what_wrong", "why_wrong", "how_to_avoid", "correct_method", "video_url", "video_start",
              "video_end", "video_caption", "source_ref", "source_text_en"}
STEP_FIELDS = ("title", "body", "body_en", "video_url", "video_caption", "video_start", "video_end", "actions",
               "estimated_minutes", "source_ref")
ERROR_FIELDS = ("title", "what_wrong", "why_wrong", "how_to_avoid", "correct_method", "video_url", "video_start",
                "video_end", "video_caption", "source_ref", "source_text_en")
ACTION_KEYS = {"key", "label_bn", "description_bn", "type"}

SCHEMA_HELP = """\
JSON format (UTF-8):

{
  "slug": "video-splitting",            required · lowercase letters, digits and hyphens
  "title": "ভিডিও স্প্লিটিং গাইড",          required · Bangla title (max 200)
  "title_en": "Video Splitting Guide",   optional · original English title
  "summary": "…",                        optional · short Bangla summary (max 500)
  "kind": "video_splitting",             optional · video_splitting | description | general
  "icon": "scissors",                    optional · Lucide icon name (default book-open-check)
  "accent": "brand",                     optional · brand | cyan | emerald | amber | rose | violet
  "source_url": "https://…",             optional · original document link (staff only)
  "project_code": null,                  optional · e.g. "ACT-01"; null = every employee
  "order": 0,                            optional · sort order on the guide list
  "sections": [                          required · at least one section
    {
      "title": "…",                      required · Bangla section title
      "title_en": "…",                   optional
      "anchor": "basics",                optional · deep-link id (#basics); generated if missing
      "intro": "…markdown…",             optional
      "steps": [
        {
          "title": "…",                  required · Bangla step title
          "anchor": "…",                 optional · generated as <section-anchor>-<n> if missing
          "body": "…markdown…",          optional · Bangla explanation; callouts: > [!RULE] / [!TIP] / [!WARNING] /
                                                   [!NOTE] / [!EXAMPLE] / [!IMPORTANT] / [!STEP]
          "body_en": "…",                optional · original English text
          "video_url": "https://…",      optional · ORIGINAL video link (YouTube, Vimeo, Drive, Loom,
                                                   Stream/SharePoint, Lark/Feishu, .mp4/.webm/.mov, .m3u8)
          "video_caption": "…",          optional · Bangla caption (max 300)
          "video_start": 90,             optional · seconds, or "1:30" — where the part of the video
          "video_end": 125,              optional   that this step's text describes starts / ends
          "actions": [                   optional · "which button does what"
            {"key": "N", "label_bn": "কাট", "description_bn": "…"}
          ],
          "estimated_minutes": 2,        optional · reading time in minutes
          "source_ref": "Doc §2, point 3 · video 01:20–02:05",   optional · where it comes from (staff only)
          "task_errors": [               optional · Task Error examples shown with this step
            {
              "title": "…",              required · short Bangla name of the mistake
              "what_wrong": "…",         required · কী ভুল হয়েছে (Markdown)
              "why_wrong": "…",          optional · কেন ভুল
              "how_to_avoid": "…",       optional · কীভাবে এড়াবেন
              "correct_method": "…",     optional · সঠিক পদ্ধতি
              "video_url": "https://…",  optional · ORIGINAL video that shows the mistake
              "video_start": "3:10", "video_end": "3:40", "video_caption": "…",
              "source_ref": "…", "source_text_en": "…",   optional · traceability (staff only)
              "anchor": "…"              optional · generated as <step-anchor>-error-<n>
            }
          ]
        }
      ]
    }
  ],
  "task_errors": [ … ]                   optional · general Task Error examples (same fields)
}
"""


class GuideImportError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


@dataclass
class ImportResult:
    guide: Guide
    created: bool
    sections: int = 0
    steps: int = 0
    steps_kept: int = 0
    steps_removed: int = 0
    progress_kept: int = 0
    task_errors: int = 0
    warnings: list = field(default_factory=list)


def load_json(raw) -> dict:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise GuideImportError(["The file is not UTF-8 encoded text."])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise GuideImportError([f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}"])


class _Validator:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, path, msg):
        self.errors.append(f"{path}: {msg}")

    def text(self, obj, key, path, *, required=False, max_len=None):
        value = obj.get(key)
        if value is None:
            if required:
                self.err(f"{path}.{key}" if path else key, "is required")
            return ""
        if not isinstance(value, str):
            self.err(f"{path}.{key}" if path else key, f"must be text, got {type(value).__name__}")
            return ""
        value = value.strip()
        if required and not value:
            self.err(f"{path}.{key}" if path else key, "must not be empty")
        if max_len and len(value) > max_len:
            self.err(f"{path}.{key}" if path else key, f"is too long ({len(value)} characters, max {max_len})")
        return value

    def url(self, obj, key, path, *, max_len):
        value = self.text(obj, key, path, max_len=max_len)
        if value and clean_url(value) is None:
            self.err(f"{path}.{key}" if path else key, f"must be an http(s) link, got {value[:80]!r}")
            return ""
        return value

    def unknown(self, obj, allowed, path):
        for k in obj:
            if k not in allowed:
                self.warnings.append(f"{path or 'top level'}: unknown field {k!r} ignored (allowed: {', '.join(sorted(allowed))})")

    def int_or_none(self, obj, key, path, *, lo=0, hi=None):
        value = obj.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            self.err(f"{path}.{key}" if path else key, f"must be a whole number or null, got {value!r}")
            return None
        if value < lo or (hi is not None and value > hi):
            self.err(f"{path}.{key}" if path else key, f"must be between {lo} and {hi}")
            return None
        return value


def validate(data) -> tuple[dict, list[str], list[str]]:
    """Returns (cleaned, errors, warnings). `cleaned` is only meaningful without errors."""
    v = _Validator()
    if not isinstance(data, dict):
        return {}, ["The file must contain one JSON object (the guide)."], []
    v.unknown(data, TOP_KEYS, "")
    g = {
        "slug": v.text(data, "slug", "", required=True, max_len=120),
        "title": v.text(data, "title", "", required=True, max_len=200),
        "title_en": v.text(data, "title_en", "", max_len=200),
        "summary": v.text(data, "summary", "", max_len=500),
        "kind": v.text(data, "kind", "") or GuideKind.GENERAL,
        "icon": v.text(data, "icon", "", max_len=40) or "book-open-check",
        "accent": v.text(data, "accent", "") or GuideAccent.BRAND,
        "source_url": v.url(data, "source_url", "", max_len=500),
        "project_code": data.get("project_code"),
        "order": v.int_or_none(data, "order", "", hi=100000),
    }
    if g["slug"] and not SLUG_RE.match(g["slug"]):
        v.err("slug", f"use lowercase letters, digits and hyphens only (e.g. video-splitting), got {g['slug']!r}")
    if g["kind"] not in GuideKind.values:
        v.err("kind", f"must be one of {', '.join(GuideKind.values)}, got {g['kind']!r}")
    if g["accent"] not in GuideAccent.values:
        v.err("accent", f"must be one of {', '.join(GuideAccent.values)}, got {g['accent']!r}")
    if g["icon"] not in ICONS:
        v.warnings.append(f"icon: unknown icon {g['icon']!r}, using 'book-open-check'")
        g["icon"] = "book-open-check"
    code = g["project_code"]
    g["project"] = None
    if code not in (None, ""):
        from apps.projects.models import Project

        if not isinstance(code, str):
            v.err("project_code", "must be a project code (text) or null")
        else:
            g["project"] = Project.objects.filter(code__iexact=code.strip()).first()
            if g["project"] is None:
                v.err("project_code", f"no project with code {code!r}")

    sections = data.get("sections")
    g["sections"] = []
    if not isinstance(sections, list) or not sections:
        v.err("sections", "must be a non-empty list of sections")
        sections = []
    taken: set[str] = set()
    explicit: dict[str, str] = {}

    def claim_anchor(raw, path):
        if raw not in (None, ""):
            if not isinstance(raw, str) or not SLUG_RE.match(raw.strip()) or len(raw.strip()) > 100:
                v.err(f"{path}.anchor", f"use up to 100 lowercase letters, digits and hyphens, got {raw!r}")
            else:
                raw = raw.strip()
                if raw in explicit:
                    v.err(f"{path}.anchor", f"{raw!r} is already used by {explicit[raw]}")
                explicit[raw] = path
                taken.add(raw)
                return raw
        return None

    # First pass: explicit anchors (so generated ones never collide with them).
    for i, sec in enumerate(sections, start=1):
        if isinstance(sec, dict):
            claim_anchor(sec.get("anchor"), f"sections[{i}]")
            for j, st in enumerate(sec.get("steps") or [], start=1):
                if isinstance(st, dict):
                    claim_anchor(st.get("anchor"), f"sections[{i}].steps[{j}]")

    total_steps = 0
    for i, sec in enumerate(sections, start=1):
        sp = f"sections[{i}]"
        if not isinstance(sec, dict):
            v.err(sp, "must be an object with a title and steps")
            continue
        v.unknown(sec, SECTION_KEYS, sp)
        s = {
            "title": v.text(sec, "title", sp, required=True, max_len=200),
            "title_en": v.text(sec, "title_en", sp, max_len=200),
            "intro": v.text(sec, "intro", sp),
            "steps": [],
        }
        raw_anchor = sec.get("anchor")
        if isinstance(raw_anchor, str) and SLUG_RE.match(raw_anchor.strip()):
            s["anchor"] = raw_anchor.strip()
        else:
            s["anchor"] = services.unique_anchor(services.section_anchor_base(s["title_en"], s["title"], i), taken, f"section-{i}")
        steps = sec.get("steps")
        if steps is None:
            steps = []
        if not isinstance(steps, list):
            v.err(f"{sp}.steps", "must be a list")
            steps = []
        if not steps:
            v.warnings.append(f"{sp}: section has no steps")
        for j, st in enumerate(steps, start=1):
            tp = f"{sp}.steps[{j}]"
            if not isinstance(st, dict):
                v.err(tp, "must be an object with at least a title")
                continue
            v.unknown(st, STEP_KEYS, tp)
            t = {
                "title": v.text(st, "title", tp, required=True, max_len=200),
                "body": v.text(st, "body", tp),
                "body_en": v.text(st, "body_en", tp),
                "video_url": v.url(st, "video_url", tp, max_len=1000),
                "video_caption": v.text(st, "video_caption", tp, max_len=300),
                "estimated_minutes": v.int_or_none(st, "estimated_minutes", tp, lo=1, hi=600),
            }
            t["source_ref"] = v.text(st, "source_ref", tp, max_len=300)
            t["video_start"], t["video_end"] = _segment(v, st, tp)
            raw_anchor = st.get("anchor")
            if isinstance(raw_anchor, str) and SLUG_RE.match(raw_anchor.strip()):
                t["anchor"] = raw_anchor.strip()
            else:
                t["anchor"] = services.unique_anchor(services.step_anchor_base(s["anchor"], t["title"], j), taken, f"{s['anchor']}-{j}")
            t["actions"] = clean_actions(st.get("actions"), f"{tp}.actions", v.errors)
            if not t["body"] and not t["video_url"]:
                v.warnings.append(f"{tp}: step has neither a body nor a video")
            t["task_errors"] = _errors(v, st.get("task_errors"), f"{tp}.task_errors", taken, t["anchor"])
            s["steps"].append(t)
            total_steps += 1
        g["sections"].append(s)
    if sections and not total_steps:
        v.warnings.append("the guide has no steps")
    g["task_errors"] = _errors(v, data.get("task_errors"), "task_errors", taken, None)
    return g, v.errors, v.warnings


def _segment(v, obj, path):
    """(start, end) seconds of the video segment, validated."""
    out = []
    for key in ("video_start", "video_end"):
        raw = obj.get(key)
        value = None
        if raw not in (None, ""):
            value = parse_start(raw) if not isinstance(raw, bool) else None
            if value is None:
                v.err(f"{path}.{key}", f"must be seconds (e.g. 90) or \"m:ss\" (e.g. \"1:30\"), got {raw!r}")
        out.append(value)
    start, end = out
    if end is not None and end <= (start or 0):
        v.err(f"{path}.video_end", "must be after video_start")
        end = None
    return start, end


def _errors(v, raw, path, taken, step_anchor):
    """Validate a task_errors list."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        v.err(path, "must be a list of Task Error examples")
        return []
    out = []
    for k, e in enumerate(raw, start=1):
        ep = f"{path}[{k}]"
        if not isinstance(e, dict):
            v.err(ep, "must be an object with at least a title and what_wrong")
            continue
        v.unknown(e, ERROR_KEYS, ep)
        row = {
            "title": v.text(e, "title", ep, required=True, max_len=200),
            "what_wrong": v.text(e, "what_wrong", ep, required=True),
            "why_wrong": v.text(e, "why_wrong", ep),
            "how_to_avoid": v.text(e, "how_to_avoid", ep),
            "correct_method": v.text(e, "correct_method", ep),
            "video_url": v.url(e, "video_url", ep, max_len=1000),
            "video_caption": v.text(e, "video_caption", ep, max_len=300),
            "source_ref": v.text(e, "source_ref", ep, max_len=300),
            "source_text_en": v.text(e, "source_text_en", ep),
        }
        row["video_start"], row["video_end"] = _segment(v, e, ep)
        if not row["correct_method"]:
            v.warnings.append(f"{ep}: no correct_method — employees should see the right way next to the mistake")
        a = e.get("anchor")
        if isinstance(a, str) and SLUG_RE.match(a.strip()) and len(a.strip()) <= 100:
            if a.strip() in taken:
                v.err(f"{ep}.anchor", f"{a.strip()!r} is already used in this guide")
            row["anchor"] = a.strip()
            taken.add(row["anchor"])
        else:
            if a not in (None, ""):
                v.err(f"{ep}.anchor", f"use up to 100 lowercase letters, digits and hyphens, got {a!r}")
            row["anchor"] = services.unique_anchor(services.error_anchor_base(step_anchor, k), taken, f"task-error-{k}")
        out.append(row)
    return out


def clean_actions(raw, path, errors: list) -> list[dict]:
    """Validate an actions list → [{"key", "label_bn", "description_bn"[, "type"]}]."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        errors.append(f"{path}: must be a list of {{\"key\", \"label_bn\", \"description_bn\"}} objects")
        return []
    out = []
    for k, a in enumerate(raw, start=1):
        ap = f"{path}[{k}]"
        if not isinstance(a, dict):
            errors.append(f"{ap}: must be an object like {{\"key\": \"N\", \"label_bn\": \"…\", \"description_bn\": \"…\"}}")
            continue
        bad = set(a) - ACTION_KEYS
        if bad:
            errors.append(f"{ap}: unknown field(s) {', '.join(sorted(bad))} (allowed: key, label_bn, description_bn, type)")
        row = {}
        for key, max_len, required in (("key", 60, True), ("label_bn", 120, False), ("description_bn", 600, False)):
            value = a.get(key)
            if value is None:
                value = ""
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                errors.append(f"{ap}.{key}: must be text")
                value = ""
            value = str(value).strip()
            if required and not value:
                errors.append(f"{ap}.{key}: is required (the key or button label, e.g. \"N\" or \"Submit & Next\")")
            if len(value) > max_len:
                errors.append(f"{ap}.{key}: is too long (max {max_len})")
            row[key] = value
        kind = a.get("type")
        if kind not in (None, ""):
            if kind not in ("key", "button"):
                errors.append(f"{ap}.type: must be \"key\" or \"button\"")
            else:
                row["type"] = kind
        out.append(row)
    return out


@transaction.atomic
def import_guide(data, *, replace=False, publish=False, user=None, dry_run=False) -> ImportResult:
    cleaned, errors, warnings = validate(data)
    if errors:
        raise GuideImportError(errors)

    guide = Guide.objects.select_for_update().filter(slug=cleaned["slug"]).first()
    created = guide is None
    if not created and not replace and guide.sections.exists():
        raise GuideImportError([
            f"slug: a guide with slug {cleaned['slug']!r} already exists ({guide.sections.count()} sections, "
            f"{guide.steps.count()} steps). Use --replace (or tick “Replace existing content”) to rebuild it."
        ])
    if created:
        guide = Guide(slug=cleaned["slug"], created_by=user if getattr(user, "is_authenticated", False) else None)
    for f in ("title", "title_en", "summary", "kind", "icon", "accent", "source_url", "project"):
        setattr(guide, f, cleaned[f])
    if cleaned["order"] is not None:
        guide.order = cleaned["order"]
    if publish:
        guide.status = ContentStatus.PUBLISHED
        guide.published_at = guide.published_at or timezone.now()
    guide.save()

    result = ImportResult(guide=guide, created=created, warnings=warnings)
    old_sections = {s.anchor: s for s in guide.sections.all()}
    old_steps = {s.anchor: s for s in GuideStep.objects.filter(guide=guide)}
    new_section_anchors = {s["anchor"] for s in cleaned["sections"]}
    new_step_anchors = {t["anchor"] for s in cleaned["sections"] for t in s["steps"]}

    # Steps that are gone are deleted (with their progress); the rest are updated in place
    # — matched by anchor — so progress on them survives a --replace.
    removed = [s.pk for a, s in old_steps.items() if a not in new_step_anchors]
    result.steps_removed = len(removed)
    GuideStep.objects.filter(pk__in=removed).delete()

    sections = {}
    for i, s in enumerate(cleaned["sections"], start=1):
        sec = old_sections.get(s["anchor"]) or GuideSection(guide=guide, anchor=s["anchor"])
        sec.order, sec.title, sec.title_en, sec.intro = i, s["title"], s["title_en"], s["intro"]
        sec.save()
        sections[s["anchor"]] = sec
        result.sections += 1

    old_errors = {e.anchor: e for e in GuideTaskError.objects.filter(guide=guide)}
    GuideTaskError.objects.filter(guide=guide).delete()  # rebuilt below (verification kept when unchanged)

    def save_errors(rows, step):
        for k, row in enumerate(rows, start=1):
            err = GuideTaskError(guide=guide, step=step, anchor=row["anchor"], order=k)
            for f in ERROR_FIELDS:
                setattr(err, f, row[f])
            old = old_errors.get(row["anchor"])
            if old is not None and not services.content_changed(services.snapshot(old), err):
                err.verified_at, err.verified_by_id = old.verified_at, old.verified_by_id
            err.save()
            result.task_errors += 1

    for s in cleaned["sections"]:
        for j, t in enumerate(s["steps"], start=1):
            st = old_steps.get(t["anchor"])
            before = None
            if st is not None:
                result.steps_kept += 1
                result.progress_kept += st.progress.count()
                before = services.snapshot(st)
            else:
                st = GuideStep(guide=guide, anchor=t["anchor"])
            st.section, st.guide, st.order = sections[s["anchor"]], guide, j
            for f in STEP_FIELDS:
                setattr(st, f, t[f])
            if services.content_changed(before, st):
                st.verified_at, st.verified_by = None, None
            st.save()
            save_errors(t["task_errors"], st)
            result.steps += 1
    save_errors(cleaned["task_errors"], None)

    # Sections that are gone (their surviving steps were moved above).
    GuideSection.objects.filter(pk__in=[s.pk for a, s in old_sections.items() if a not in new_section_anchors]).delete()
    if dry_run:
        transaction.set_rollback(True)
    return result


def export_guide(guide) -> dict:
    """The guide in the import format (round-trips through import_guide)."""
    out = {
        "slug": guide.slug, "title": guide.title, "title_en": guide.title_en, "summary": guide.summary,
        "kind": guide.kind, "icon": guide.icon, "accent": guide.accent, "source_url": guide.source_url,
        "project_code": guide.project.code if guide.project_id else None, "order": guide.order, "sections": [],
    }
    steps, errors = {}, {}
    for st in GuideStep.objects.filter(guide=guide).order_by("order", "pk"):
        steps.setdefault(st.section_id, []).append(st)
    for e in GuideTaskError.objects.filter(guide=guide).order_by("order", "pk"):
        errors.setdefault(e.step_id, []).append({"anchor": e.anchor, **{f: getattr(e, f) for f in ERROR_FIELDS}})
    for sec in guide.sections.all():
        out["sections"].append({
            "title": sec.title, "title_en": sec.title_en, "anchor": sec.anchor, "intro": sec.intro,
            "steps": [{
                "anchor": st.anchor, **{f: (getattr(st, f) or [] if f == "actions" else getattr(st, f)) for f in STEP_FIELDS},
                "task_errors": errors.get(st.pk, []),
            } for st in steps.get(sec.pk, [])],
        })
    out["task_errors"] = errors.get(None, [])
    return out


__all__ = ["GuideImportError", "ImportResult", "SCHEMA_HELP", "export_guide", "import_guide", "load_json", "validate"]
