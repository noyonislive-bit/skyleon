"""Business logic for work guides: visibility, outline/numbering, progress, anchors."""

import math
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.permissions import can_manage_content_for, has_permission, scoped_project_ids
from apps.core.choices import ContentStatus

from .models import Guide, GuideProgress, GuideSection, GuideStep, GuideTaskError
from .video import embed_info

BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
WORDS_PER_MINUTE = 120  # comfortable reading pace for Bangla instructions


def bn(value) -> str:
    """Western digits → Bangla digits ("1.2" → "১.২")."""
    return str(value).translate(BN_DIGITS)


# ── Visibility ──────────────────────────────────────────────────────────────

def visible_guides(user):
    """Published guides for the user's projects plus company-wide guides."""
    project_ids = list(user.memberships.values_list("project_id", flat=True))
    return Guide.objects.filter(status=ContentStatus.PUBLISHED).filter(
        Q(project__isnull=True) | Q(project_id__in=project_ids)
    ).select_related("project")


def manageable_guides(user):
    ids = scoped_project_ids(user)
    qs = Guide.objects.select_related("project", "created_by")
    if ids is None:
        return qs
    return qs.filter(Q(project__isnull=True) | Q(project_id__in=ids))


def can_edit(user, guide) -> bool:
    return can_manage_content_for(user, guide.project)


def readable_guide(user, slug):
    """(guide, is_preview) for the reader, or (None, False). Staff can preview drafts they manage."""
    guide = visible_guides(user).filter(slug=slug).first()
    if guide is not None:
        return guide, False
    if has_permission(user, "content.manage"):
        guide = manageable_guides(user).filter(slug=slug).first()
        if guide is not None:
            return guide, True
    return None, False


# ── Anchors ─────────────────────────────────────────────────────────────────

ANCHOR_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def clean_anchor(value) -> str:
    return slugify(str(value or ""))[:100].strip("-")


def taken_anchors(guide, exclude=None) -> set[str]:
    """Section, step and Task Error anchors share one namespace per guide (all are #fragments of the same page)."""
    sec = GuideSection.objects.filter(guide=guide)
    stp = GuideStep.objects.filter(guide=guide)
    err = GuideTaskError.objects.filter(guide=guide)
    if isinstance(exclude, GuideSection) and exclude.pk:
        sec = sec.exclude(pk=exclude.pk)
    if isinstance(exclude, GuideStep) and exclude.pk:
        stp = stp.exclude(pk=exclude.pk)
    if isinstance(exclude, GuideTaskError) and exclude.pk:
        err = err.exclude(pk=exclude.pk)
    return (set(sec.values_list("anchor", flat=True)) | set(stp.values_list("anchor", flat=True))
            | set(err.values_list("anchor", flat=True)) | {TASK_ERRORS_ANCHOR})


def unique_anchor(base: str, taken: set[str], fallback: str) -> str:
    base = clean_anchor(base) or clean_anchor(fallback) or "part"
    anchor, n = base, 2
    while anchor in taken:
        anchor = f"{base}-{n}"
        n += 1
    taken.add(anchor)
    return anchor


def section_anchor_base(title_en: str, title: str, number: int) -> str:
    """English title when there is one, otherwise the (ASCII part of the) title, otherwise section-N."""
    return clean_anchor(title_en) or (clean_anchor(title) if title.isascii() else "") or f"section-{number}"


def step_anchor_base(section_anchor: str, title: str, number: int) -> str:
    return (clean_anchor(title) if title.isascii() else "") or f"{section_anchor}-{number}"


TASK_ERRORS_ANCHOR = "task-errors"  # the "all Task Error examples" block at the end of a guide


def error_anchor_base(step_anchor: str | None, number: int) -> str:
    return f"{step_anchor}-error-{number}" if step_anchor else f"task-error-{number}"


# ── Source of truth: verification against the original document + video ─────

def content_changed(before: dict | None, obj) -> bool:
    """True when any field that must match the original changed since `before` (a snapshot)."""
    if before is None:
        return True
    return any(before.get(f) != getattr(obj, f) for f in obj.VERIFIED_FIELDS)


def snapshot(obj) -> dict:
    return {f: getattr(obj, f) for f in obj.VERIFIED_FIELDS}


def apply_verification(obj, before: dict | None, *, ticked: bool, was_ticked: bool, user) -> bool:
    """Verification from an edit form's checkbox. A content change always clears an existing mark
    (the box was already ticked, so leaving it ticked is not a fresh check); ticking the box
    afresh verifies; unticking clears. Returns True when an existing mark was dropped by an edit."""
    changed = content_changed(before, obj)
    if ticked and not was_ticked:
        obj.verified_at, obj.verified_by = timezone.now(), user
    elif not ticked or changed:
        dropped = bool(obj.verified_at) and ticked and changed
        obj.verified_at, obj.verified_by = None, None
        return dropped
    return False


def set_verified(obj, user, verified: bool):
    obj.verified_at = timezone.now() if verified else None
    obj.verified_by = user if verified else None
    type(obj).objects.filter(pk=obj.pk).update(verified_at=obj.verified_at, verified_by=obj.verified_by)
    return obj


def verification_stats(guide) -> dict:
    steps = GuideStep.objects.filter(guide=guide)
    errors = GuideTaskError.objects.filter(guide=guide)
    total = steps.count() + errors.count()
    verified = steps.filter(verified_at__isnull=False).count() + errors.filter(verified_at__isnull=False).count()
    return {"total": total, "verified": verified, "pending": total - verified,
            "percent": round(verified * 100 / total) if total else 0, "complete": total > 0 and verified == total}


# ── Ordering helpers ────────────────────────────────────────────────────────

def next_order(qs) -> int:
    return (qs.aggregate(m=Max("order"))["m"] or 0) + 1


def error_siblings(err):
    qs = GuideTaskError.objects.filter(guide_id=err.guide_id)
    return qs.filter(step_id=err.step_id) if err.step_id else qs.filter(step__isnull=True)


@transaction.atomic
def move(obj, direction: int) -> bool:
    """Swap a section (within its guide), a step (within its section) or a Task Error example
    (within its step) with its neighbour."""
    if isinstance(obj, GuideSection):
        siblings = list(obj.guide.sections.all())
    elif isinstance(obj, GuideTaskError):
        siblings = list(error_siblings(obj))
    else:
        siblings = list(obj.section.steps.all())
    for i, s in enumerate(siblings, start=1):  # normalise orders first (ties / gaps)
        if s.order != i:
            type(s).objects.filter(pk=s.pk).update(order=i)
            s.order = i
    idx = next(i for i, s in enumerate(siblings) if s.pk == obj.pk)
    j = idx + (1 if direction > 0 else -1)
    if j < 0 or j >= len(siblings):
        return False
    a, b = siblings[idx], siblings[j]
    type(a).objects.filter(pk=a.pk).update(order=b.order)
    type(b).objects.filter(pk=b.pk).update(order=a.order)
    return True


def renumber(qs):
    for i, obj in enumerate(qs, start=1):
        if obj.order != i:
            type(obj).objects.filter(pk=obj.pk).update(order=i)


# ── Outline (numbering, progress, navigation) ───────────────────────────────

def step_minutes(step) -> int:
    if step.estimated_minutes:
        return int(step.estimated_minutes)
    words = len(re.findall(r"\S+", step.body or ""))
    return max(1, math.ceil(words / WORDS_PER_MINUTE) + (1 if step.video_url else 0))


@dataclass(eq=False)
class StepNode:
    obj: GuideStep
    section: "SectionNode"
    number: str  # "1.2"
    index: int  # 1-based position in the whole guide
    done: bool = False
    prev: "StepNode | None" = None
    next: "StepNode | None" = None

    @property
    def label(self):
        return bn(self.number)

    @property
    def anchor(self):
        return self.obj.anchor

    @property
    def minutes(self):
        return step_minutes(self.obj)

    @property
    def video(self):
        if not hasattr(self, "_video"):
            self._video = embed_info(self.obj.video_url, self.obj.video_start, self.obj.video_end) if self.obj.video_url else None
        return self._video

    errors: list = field(default_factory=list)


@dataclass(eq=False)
class ErrorNode:
    """A Task Error example in reading order (numbered across the whole guide: ভুল ১, ভুল ২ …)."""
    obj: GuideTaskError
    number: int
    step: "StepNode | None" = None

    @property
    def label(self):
        return bn(self.number)

    @property
    def anchor(self):
        return self.obj.anchor

    @property
    def video(self):
        if not hasattr(self, "_video"):
            self._video = embed_info(self.obj.video_url, self.obj.video_start, self.obj.video_end) if self.obj.video_url else None
        return self._video


@dataclass(eq=False)
class SectionNode:
    obj: GuideSection
    number: int
    steps: list = field(default_factory=list)

    @property
    def label(self):
        return bn(self.number)

    @property
    def anchor(self):
        return self.obj.anchor

    @property
    def done_count(self):
        return sum(1 for s in self.steps if s.done)

    @property
    def is_done(self):
        return bool(self.steps) and self.done_count == len(self.steps)


@dataclass(eq=False)
class Outline:
    guide: Guide
    sections: list
    steps: list
    done_ids: set
    errors: list = field(default_factory=list)  # every Task Error example, in reading order

    @property
    def guide_errors(self):
        """General Task Error examples (not tied to one step)."""
        return [e for e in self.errors if e.step is None]

    @property
    def error_count(self):
        return len(self.errors)

    @property
    def errors_anchor(self):
        return TASK_ERRORS_ANCHOR

    @property
    def total(self):
        return len(self.steps)

    @property
    def done_count(self):
        return sum(1 for s in self.steps if s.done)

    @property
    def percent(self):
        return round(self.done_count * 100 / self.total) if self.total else 0

    @property
    def minutes(self):
        return sum(s.minutes for s in self.steps)

    @property
    def remaining_minutes(self):
        return sum(s.minutes for s in self.steps if not s.done)

    @property
    def remaining_count(self):
        return self.total - self.done_count

    @property
    def video_count(self):
        return sum(1 for s in self.steps if s.obj.video_url)

    @property
    def first_unread(self):
        return next((s for s in self.steps if not s.done), None)

    @property
    def is_complete(self):
        return bool(self.steps) and self.done_count == self.total

    @property
    def started(self):
        return self.done_count > 0

    def step(self, anchor):
        return next((s for s in self.steps if s.anchor == anchor), None)

    def section(self, anchor):
        return next((s for s in self.sections if s.anchor == anchor), None)


def build_outline(guide, user=None) -> Outline:
    sections = list(guide.sections.all())
    steps = list(GuideStep.objects.filter(guide=guide).order_by("section__order", "section_id", "order", "pk"))
    done_ids = set()
    if user is not None and getattr(user, "is_authenticated", False):
        done_ids = set(GuideProgress.objects.filter(user=user, step__guide=guide).values_list("step_id", flat=True))
    by_section = {}
    for st in steps:
        by_section.setdefault(st.section_id, []).append(st)
    sec_nodes, step_nodes = [], []
    for i, sec in enumerate(sections, start=1):
        node = SectionNode(obj=sec, number=i)
        for j, st in enumerate(by_section.get(sec.pk, []), start=1):
            sn = StepNode(obj=st, section=node, number=f"{i}.{j}", index=len(step_nodes) + 1, done=st.pk in done_ids)
            node.steps.append(sn)
            step_nodes.append(sn)
        sec_nodes.append(node)
    for a, b in zip(step_nodes, step_nodes[1:]):
        a.next, b.prev = b, a
    by_step = {sn.obj.pk: sn for sn in step_nodes}
    raw_errors = list(GuideTaskError.objects.filter(guide=guide).order_by("order", "pk"))
    errs_by_step = {}
    for e in raw_errors:
        errs_by_step.setdefault(e.step_id, []).append(e)
    error_nodes = []
    for sn in step_nodes:  # step examples in reading order, then the general ones
        for e in errs_by_step.get(sn.obj.pk, []):
            en = ErrorNode(obj=e, number=len(error_nodes) + 1, step=sn)
            sn.errors.append(en)
            error_nodes.append(en)
    for e in errs_by_step.get(None, []):
        error_nodes.append(ErrorNode(obj=e, number=len(error_nodes) + 1))
    return Outline(guide=guide, sections=sec_nodes, steps=step_nodes, done_ids=done_ids, errors=error_nodes)


def guide_stats(guides, user) -> dict:
    """{guide_id: {"total", "done", "percent", "minutes", "sections", "errors", "first_unread": anchor|None}} in 4 queries."""
    guides = list(guides)
    ids = [g.pk for g in guides]
    out = {g.pk: {"total": 0, "done": 0, "percent": 0, "minutes": 0, "sections": 0, "errors": 0, "first_unread": None, "first": None}
           for g in guides}
    for sec in GuideSection.objects.filter(guide_id__in=ids).values("guide_id"):
        out[sec["guide_id"]]["sections"] += 1
    for err in GuideTaskError.objects.filter(guide_id__in=ids).values("guide_id"):
        out[err["guide_id"]]["errors"] += 1
    done = set(GuideProgress.objects.filter(user=user, step__guide_id__in=ids).values_list("step_id", flat=True))
    steps = GuideStep.objects.filter(guide_id__in=ids).only(
        "id", "guide_id", "anchor", "body", "video_url", "estimated_minutes", "order", "section_id"
    ).order_by("section__order", "section_id", "order", "pk")
    for st in steps:
        row = out[st.guide_id]
        row["total"] += 1
        row["minutes"] += step_minutes(st)
        row["first"] = row["first"] or st.anchor
        if st.pk in done:
            row["done"] += 1
        elif row["first_unread"] is None:
            row["first_unread"] = st.anchor
    for row in out.values():
        row["percent"] = round(row["done"] * 100 / row["total"]) if row["total"] else 0
    return out


# ── Progress ────────────────────────────────────────────────────────────────

def set_done(user, step, done: bool) -> bool:
    if done:
        GuideProgress.objects.get_or_create(user=user, step=step)
    else:
        GuideProgress.objects.filter(user=user, step=step).delete()
    return done


def progress_payload(user, step) -> dict:
    guide_steps = GuideStep.objects.filter(guide_id=step.guide_id)
    done_ids = set(GuideProgress.objects.filter(user=user, step__guide_id=step.guide_id).values_list("step_id", flat=True))
    total = guide_steps.count()
    section_ids = list(guide_steps.filter(section_id=step.section_id).values_list("id", flat=True))
    done_count = len(done_ids)
    return {
        "ok": True,
        "stepId": step.pk,
        "anchor": step.anchor,
        "done": step.pk in done_ids,
        "doneCount": done_count,
        "total": total,
        "percent": round(done_count * 100 / total) if total else 0,
        "complete": total > 0 and done_count >= total,
        "section": {
            "anchor": step.section.anchor,
            "done": sum(1 for i in section_ids if i in done_ids),
            "total": len(section_ids),
        },
    }
