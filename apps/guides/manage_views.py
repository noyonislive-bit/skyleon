"""Admin side of the work guides (/admin/guides/)."""

import json
from collections import defaultdict

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.models import Role, UserStatus
from apps.accounts.permissions import can_manage_content_for, scoped_project_ids
from apps.core import audit
from apps.core.choices import ContentStatus
from apps.core.icons import ICONS
from apps.projects.models import Project

from . import services
from .forms import GuideForm, ImportForm, SectionForm, StepForm, TaskErrorForm
from .importer import SCHEMA_HELP, GuideImportError, export_guide, import_guide, load_json
from .models import Guide, GuideProgress, GuideSection, GuideStep, GuideTaskError
from .video import clean_url, describe, embed_info, parse_start

ADMIN_LABEL = "Work guides"


def _projects_for(user):
    ids = scoped_project_ids(user)
    qs = Project.objects.order_by("name")
    return qs if ids is None else qs.filter(pk__in=ids)


def _guide_or_404(request, pk, *, edit=True):
    guide = services.manageable_guides(request.user).filter(pk=pk).first()
    if guide is None or (edit and not can_manage_content_for(request.user, guide.project)):
        raise Http404
    return guide


def _section_or_404(request, section_id):
    section = get_object_or_404(GuideSection.objects.select_related("guide"), pk=section_id)
    _guide_or_404(request, section.guide_id)
    return section


def _step_or_404(request, step_id):
    step = get_object_or_404(GuideStep.objects.select_related("guide", "section"), pk=step_id)
    _guide_or_404(request, step.guide_id)
    return step


def _error_or_404(request, error_id):
    err = get_object_or_404(GuideTaskError.objects.select_related("guide", "step"), pk=error_id)
    _guide_or_404(request, err.guide_id)
    return err


def _editor_url(guide, anchor=""):
    return reverse("guides:manage_edit", args=[guide.pk]) + (f"#{anchor}" if anchor else "")


def _reader_stats(guides):
    """{guide_id: {"readers", "completed", "avg"}} from GuideProgress."""
    ids = [g.pk for g in guides]
    totals = {g.pk: getattr(g, "n_steps", None) or g.steps.count() for g in guides}
    per_user = (GuideProgress.objects.filter(step__guide_id__in=ids)
                .values("step__guide_id", "user_id").annotate(n=Count("id"), last=Max("read_at")))
    out = defaultdict(lambda: {"readers": 0, "completed": 0, "avg": None, "sum": 0.0})
    for row in per_user:
        gid = row["step__guide_id"]
        total = totals.get(gid) or 0
        stat = out[gid]
        stat["readers"] += 1
        if total:
            stat["sum"] += min(row["n"], total) / total
            stat["completed"] += row["n"] >= total
    for stat in out.values():
        stat["avg"] = round(stat["sum"] * 100 / stat["readers"]) if stat["readers"] else None
    return out


@permission_required_code("content.manage")
def manage_list(request):
    guides = list(services.manageable_guides(request.user).annotate(
        n_sections=Count("sections", distinct=True), n_steps=Count("steps", distinct=True)))
    stats = _reader_stats(guides)
    rows = [{"guide": g, "can_edit": can_manage_content_for(request.user, g.project), **stats[g.pk]} for g in guides]
    return render(request, "guides/manage/list.html", {
        "rows": rows,
        "page_title": ADMIN_LABEL,
        "page_subtitle": "Step-by-step Bangla work documents with original videos. Employees mark each step as understood.",
        "crumbs": [(ADMIN_LABEL, "")],
    })


@permission_required_code("content.manage")
def guide_form(request, pk=None):
    guide = _guide_or_404(request, pk) if pk else None
    form = GuideForm(request.POST or None, instance=guide, projects=_projects_for(request.user))
    if request.method == "POST" and form.is_valid():
        if not can_manage_content_for(request.user, form.cleaned_data.get("project")):
            form.add_error("project", "You can only create guides for your own projects.")
        else:
            obj = form.save(commit=False)
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            audit.log(request, "guide.save", obj)
            messages.success(request, "Guide saved." if guide else "Guide created. Next: add sections and steps.")
            return redirect("guides:manage_edit", pk=obj.pk)
    if guide is None:
        return render(request, "guides/manage/guide_new.html", {
            "form": form, "icons": sorted(ICONS), "page_title": "New guide",
            "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), ("New guide", "")],
        })
    return _editor(request, guide, form)


def _editor(request, guide, form):
    outline = services.build_outline(guide)
    return render(request, "guides/manage/editor.html", {
        "guide": guide, "form": form, "outline": outline, "icons": sorted(ICONS),
        "verification": services.verification_stats(guide),
        "page_title": guide.title,
        "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), (guide.title, "")],
    })


@permission_required_code("content.manage")
@require_POST
def publish(request, pk):
    guide = _guide_or_404(request, pk)
    if request.POST.get("action") == "unpublish":
        guide.status = ContentStatus.DRAFT
        guide.save(update_fields=["status", "updated_at"])
        messages.info(request, "Guide moved back to draft — employees no longer see it.")
    else:
        if not guide.steps.exists():
            messages.error(request, "Add at least one step before publishing.")
            return redirect("guides:manage_edit", pk=guide.pk)
        check = services.verification_stats(guide)
        if check["pending"] and request.POST.get("force") != "1":
            messages.error(request, f"{check['pending']} step(s) / Task Error example(s) are not yet verified against the original "
                                    "document and video. Verify them first, or use “Publish anyway”.")
            return redirect("guides:manage_edit", pk=guide.pk)
        guide.publish()
        messages.success(request, "Guide published." if not check["pending"]
                         else f"Guide published — {check['pending']} item(s) still need to be verified against the original.")
    audit.log(request, "guide.publish", guide, status=guide.status)
    return redirect(request.POST.get("next") or reverse("guides:manage_edit", args=[guide.pk]))


@permission_required_code("content.manage")
@require_POST
def delete(request, pk):
    guide = _guide_or_404(request, pk)
    audit.log(request, "guide.delete", guide, title=guide.title, slug=guide.slug)
    guide.delete()
    messages.success(request, "Guide deleted.")
    return redirect("guides:manage")


# ── Sections ────────────────────────────────────────────────────────────────

@permission_required_code("content.manage")
def section_form(request, pk=None, section_id=None):
    section = _section_or_404(request, section_id) if section_id else None
    guide = section.guide if section else _guide_or_404(request, pk)
    form = SectionForm(request.POST or None, instance=section, guide=guide)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.anchor = form.cleaned_data["anchor"]
        if not obj.pk:
            obj.guide = guide
            obj.order = services.next_order(guide.sections.all())
        obj.save()
        audit.log(request, "guide.section.save", obj, guide=guide.pk)
        messages.success(request, "Section saved.")
        return redirect(_editor_url(guide, obj.anchor))
    return render(request, "guides/manage/section_form.html", {
        "form": form, "guide": guide, "section": section,
        "page_title": f"Edit section · {section.title}" if section else "New section",
        "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), (guide.title, _editor_url(guide)),
                   (section.title if section else "New section", "")],
    })


@permission_required_code("content.manage")
@require_POST
def section_delete(request, section_id):
    section = _section_or_404(request, section_id)
    guide = section.guide
    audit.log(request, "guide.section.delete", section, guide=guide.pk, title=section.title)
    section.delete()
    services.renumber(guide.sections.all())
    messages.success(request, "Section deleted with its steps.")
    return redirect(_editor_url(guide))


@permission_required_code("content.manage")
@require_POST
def section_move(request, section_id):
    section = _section_or_404(request, section_id)
    services.move(section, 1 if request.POST.get("direction") == "down" else -1)
    return redirect(_editor_url(section.guide, section.anchor))


# ── Steps ───────────────────────────────────────────────────────────────────

@permission_required_code("content.manage")
def step_form(request, section_id=None, step_id=None):
    step = _step_or_404(request, step_id) if step_id else None
    section = step.section if step else _section_or_404(request, section_id)
    guide = section.guide
    initial = {} if step else {"section": section}
    form = StepForm(request.POST or None, instance=step, guide=guide, initial=initial, user=request.user)
    before = services.snapshot(step) if step else None
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.anchor = form.cleaned_data["anchor"]
        obj.actions = form.cleaned_data["actions"]
        obj.video_start, obj.video_end = form.cleaned_data["video_start"], form.cleaned_data["video_end"]
        dropped = services.apply_verification(obj, before, ticked=request.POST.get("verified") == "1",
                                              was_ticked=request.POST.get("was_verified") == "1", user=request.user)
        moved = step is not None and step.section_id != form.cleaned_data["section"].pk
        if not obj.pk or moved:
            obj.order = services.next_order(form.cleaned_data["section"].steps.all())
        obj.guide = guide
        obj.save()
        if moved:
            services.renumber(section.steps.all())
        audit.log(request, "guide.step.save", obj, guide=guide.pk, verified=bool(obj.verified_at))
        messages.success(request, "Step saved." + (" It changed, so check it against the original again and tick “Verified”."
                                                   if dropped else ""))
        if request.POST.get("then") == "add":
            return redirect("guides:manage_step_new", section_id=obj.section_id)
        if request.POST.get("then") == "stay":
            return redirect("guides:manage_step_edit", step_id=obj.pk)
        return redirect(_editor_url(guide, obj.anchor))
    info = (embed_info(form["video_url"].value(), form["video_start"].value(), form["video_end"].value())
            if form["video_url"].value() else None)
    return render(request, "guides/manage/step_form.html", {
        "form": form, "guide": guide, "section": section, "step": step,
        "video_info": info, "video_label": describe(info) if form["video_url"].value() else "",
        "preview_url": (f"{guide.get_absolute_url()}#{step.anchor}" if step else ""),
        "page_title": f"Edit step · {step.title}" if step else "New step",
        "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), (guide.title, _editor_url(guide)),
                   (step.title if step else "New step", "")],
    })


@permission_required_code("content.manage")
@require_POST
def step_delete(request, step_id):
    step = _step_or_404(request, step_id)
    guide, section = step.guide, step.section
    audit.log(request, "guide.step.delete", step, guide=guide.pk, title=step.title)
    step.delete()
    services.renumber(section.steps.all())
    messages.success(request, "Step deleted.")
    return redirect(_editor_url(guide, section.anchor))


@permission_required_code("content.manage")
@require_POST
def step_move(request, step_id):
    step = _step_or_404(request, step_id)
    services.move(step, 1 if request.POST.get("direction") == "down" else -1)
    return redirect(_editor_url(step.guide, step.anchor))


# ── Task Error examples ─────────────────────────────────────────────────────

@permission_required_code("content.manage")
def error_form(request, pk=None, error_id=None):
    err = _error_or_404(request, error_id) if error_id else None
    guide = err.guide if err else _guide_or_404(request, pk)
    initial = {}
    if err is None and request.GET.get("step"):
        initial["step"] = GuideStep.objects.filter(guide=guide, pk=request.GET["step"]).first()
    form = TaskErrorForm(request.POST or None, instance=err, guide=guide, initial=initial, user=request.user)
    before = services.snapshot(err) if err else None
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.anchor = form.cleaned_data["anchor"]
        obj.video_start, obj.video_end = form.cleaned_data["video_start"], form.cleaned_data["video_end"]
        obj.guide = guide
        moved = err is not None and err.step_id != (obj.step.pk if obj.step else None)
        if err is None or moved:
            obj.order = services.next_order(GuideTaskError.objects.filter(guide=guide, step=obj.step))
        dropped = services.apply_verification(obj, before, ticked=request.POST.get("verified") == "1",
                                              was_ticked=request.POST.get("was_verified") == "1", user=request.user)
        obj.save()
        audit.log(request, "guide.task_error.save", obj, guide=guide.pk, verified=bool(obj.verified_at))
        messages.success(request, "Task Error example saved." + (" It changed, so check it against the original again and tick “Verified”."
                                                                 if dropped else ""))
        if request.POST.get("then") == "add":
            return redirect(reverse("guides:manage_error_new", args=[guide.pk]) + (f"?step={obj.step_id}" if obj.step_id else ""))
        return redirect(_editor_url(guide, obj.anchor))
    info = (embed_info(form["video_url"].value(), form["video_start"].value(), form["video_end"].value())
            if form["video_url"].value() else None)
    title = err.title if err else "New Task Error example"
    return render(request, "guides/manage/error_form.html", {
        "form": form, "guide": guide, "error": err,
        "video_info": info, "video_label": describe(info) if form["video_url"].value() else "",
        "preview_url": f"{guide.get_absolute_url()}#{err.anchor}" if err else "",
        "page_title": f"Task Error example · {title}" if err else title,
        "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), (guide.title, _editor_url(guide)), (title, "")],
    })


@permission_required_code("content.manage")
@require_POST
def error_delete(request, error_id):
    err = _error_or_404(request, error_id)
    guide, anchor = err.guide, (err.step.anchor if err.step_id else "")
    audit.log(request, "guide.task_error.delete", err, guide=guide.pk, title=err.title)
    siblings = services.error_siblings(err).exclude(pk=err.pk)
    err.delete()
    services.renumber(siblings)
    messages.success(request, "Task Error example deleted.")
    return redirect(_editor_url(guide, anchor))


@permission_required_code("content.manage")
@require_POST
def error_move(request, error_id):
    err = _error_or_404(request, error_id)
    services.move(err, 1 if request.POST.get("direction") == "down" else -1)
    return redirect(_editor_url(err.guide, err.anchor))


@permission_required_code("content.manage")
@require_POST
def verify(request, kind, obj_id):
    """Mark a step / Task Error example as checked against the original document and video (or undo)."""
    if kind not in ("step", "error"):
        raise Http404
    obj = _step_or_404(request, obj_id) if kind == "step" else _error_or_404(request, obj_id)
    verified = request.POST.get("verified", "1") == "1"
    services.set_verified(obj, request.user, verified)
    audit.log(request, f"guide.{'step' if kind == 'step' else 'task_error'}.verify", obj, guide=obj.guide_id, verified=verified)
    messages.success(request, ("Marked as verified against the original: " if verified else "Verification removed: ") + obj.title)
    return redirect(_editor_url(obj.guide, obj.anchor))


# ── Video segments (one screen for all steps and Task Error examples) ──────────

def player_source(*, url="", asset=None, user=None) -> dict | None:
    """What the segment editor's player needs for a video: kind (video / hls / youtube / vimeo /
    iframe / link), where to load it from and how to label it."""
    from apps.storage.services import media_url

    if asset is not None:
        src = media_url(asset, user)
        if not src:
            return None
        return {"key": f"asset:{asset.pk}", "asset": str(asset.pk), "url": "", "src": src,
                "kind": "hls" if asset.is_hls else "video", "label": f"Uploaded · {asset.original_name or 'video'}",
                "duration": asset.duration_sec}
    info = embed_info(url) if url else None
    if info is None:
        return None
    kind = info["kind"]
    if kind == "iframe" and info["provider"] in ("youtube", "vimeo"):
        kind = info["provider"]
    host = (url.split("//", 1)[-1].split("/", 1)[0]).removeprefix("www.")
    return {"key": f"url:{url}", "asset": "", "url": url, "src": info["src"].split("#", 1)[0], "kind": kind,
            "video_id": info.get("video_id", ""), "hash": info.get("vimeo_hash", ""),
            "label": f"{info['provider_label']} · {host}", "duration": None}


def _segment_items(guide, user):
    outline = services.build_outline(guide)
    items, sources = [], {}

    def add(obj, kind, number, title, section):
        src = player_source(url=obj.video_url, asset=obj.video_asset, user=user) if obj.has_video else None
        if src:
            sources.setdefault(src["key"], src)
        items.append({"type": kind, "id": obj.pk, "number": number, "title": title, "section": section,
                      "anchor": obj.anchor, "video": src["key"] if src else "", "start": obj.video_start,
                      "end": obj.video_end, "verified": bool(obj.verified_at)})

    for sec in outline.sections:
        for node in sec.steps:
            add(node.obj, "step", node.number, node.obj.title, f"{sec.number}. {sec.obj.title}")
            for err in node.errors:
                add(err.obj, "error", f"{node.number} · TE{err.number}", err.obj.title, f"{sec.number}. {sec.obj.title}")
    for err in outline.guide_errors:
        add(err.obj, "error", f"TE{err.number}", err.obj.title, "General Task Error examples")
    return items, sources


@permission_required_code("content.manage")
def segments(request, pk):
    from apps.backoffice.forms import MediaAssetField
    from apps.backoffice.media import content_assets
    from apps.storage.models import MediaAsset, MediaKind, MediaStatus
    from django import forms as dj_forms

    guide = _guide_or_404(request, pk)
    items, sources = _segment_items(guide, request.user)
    library = content_assets(request.user, MediaAsset.objects.filter(kind=MediaKind.VIDEO, status=MediaStatus.READY))
    for asset in library.order_by("-created_at")[:100]:
        src = player_source(asset=asset, user=request.user)
        if src:
            sources.setdefault(src["key"], {**src, "library": True})

    class UploadForm(dj_forms.Form):
        video = MediaAssetField(label="Upload a new video")

    return render(request, "guides/manage/segments.html", {
        "guide": guide, "upload_form": UploadForm(),
        "payload": {"items": items, "sources": list(sources.values()),
                    "saveUrl": reverse("guides:manage_segments_save", args=[guide.pk]),
                    "infoUrl": reverse("guides:manage_video_info"), "focus": request.GET.get("item", "")},
        "page_title": f"Video segments · {guide.title}",
        "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), (guide.title, _editor_url(guide)), ("Video segments", "")],
    })


@permission_required_code("content.manage")
@require_POST
def segments_save(request, pk):
    """Save the video + segment of many steps / Task Error examples at once (JSON)."""
    from apps.backoffice.media import can_attach_asset
    from apps.storage.models import MediaAsset, MediaKind, MediaStatus

    guide = _guide_or_404(request, pk)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)
    rows = data.get("items") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return JsonResponse({"ok": False, "error": "items must be a list."}, status=400)
    models = {"step": GuideStep, "error": GuideTaskError}
    errors, changed = [], 0
    with transaction.atomic():
        for i, row in enumerate(rows[:1000]):
            if not isinstance(row, dict) or row.get("type") not in models:
                errors.append(f"row {i + 1}: unknown item")
                continue
            obj = models[row["type"]].objects.filter(guide=guide, pk=row.get("id")).first()
            if obj is None:
                errors.append(f"row {i + 1}: not part of this guide")
                continue
            before = services.snapshot(obj)
            source = row.get("source")
            if source is None or source == {}:
                obj.video_url, obj.video_asset = "", None
            elif isinstance(source, dict) and source.get("asset"):
                asset = MediaAsset.objects.filter(pk=str(source["asset"]), kind=MediaKind.VIDEO, status=MediaStatus.READY).first() \
                    if _is_uuid(source["asset"]) else None
                if asset is None or not (asset.pk == obj.video_asset_id or can_attach_asset(request.user, asset)):
                    errors.append(f"{obj.title}: that uploaded video is not available")
                    continue
                obj.video_url, obj.video_asset = "", asset
            elif isinstance(source, dict) and source.get("url"):
                url = str(source["url"]).strip()
                if clean_url(url) is None or len(url) > 1000:
                    errors.append(f"{obj.title}: not a valid http(s) video link")
                    continue
                obj.video_url, obj.video_asset = url, None
            start, end = parse_start(row.get("start")), parse_start(row.get("end"))
            if end is not None and end <= (start or 0):
                errors.append(f"{obj.title}: the end must be after the start")
                continue
            obj.video_start, obj.video_end = start, end
            if services.content_changed(before, obj):
                obj.verified_at, obj.verified_by = None, None  # must be checked against the original again
                obj.save()
                changed += 1
    audit.log(request, "guide.segments.save", guide, changed=changed)
    return JsonResponse({"ok": not errors, "changed": changed, "errors": errors[:20]})


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


# ── Progress ────────────────────────────────────────────────────────────────

@permission_required_code("content.manage")
def progress(request, pk):
    guide = _guide_or_404(request, pk, edit=False)
    outline = services.build_outline(guide)
    step_section = {s.obj.pk: s.section.number for s in outline.steps}
    from django.contrib.auth import get_user_model

    User = get_user_model()
    people = User.objects.filter(role=Role.EMPLOYEE, status=UserStatus.ACTIVE)
    if guide.project_id:
        people = people.filter(memberships__project_id=guide.project_id)
    readers = set(GuideProgress.objects.filter(step__guide=guide).values_list("user_id", flat=True))
    users = {u.pk: u for u in people.distinct()}
    users.update({u.pk: u for u in User.objects.filter(pk__in=readers - set(users))})
    done = defaultdict(lambda: {"steps": set(), "last": None})
    for p in GuideProgress.objects.filter(step__guide=guide).values("user_id", "step_id", "read_at"):
        row = done[p["user_id"]]
        row["steps"].add(p["step_id"])
        row["last"] = max(filter(None, [row["last"], p["read_at"]]))
    total = outline.total
    rows = []
    for u in users.values():
        d = done.get(u.pk, {"steps": set(), "last": None})
        per_section = []
        for sec in outline.sections:
            n = sum(1 for s in sec.steps if s.obj.pk in d["steps"])
            per_section.append({"done": n, "total": len(sec.steps)})
        n_done = len([sid for sid in d["steps"] if sid in step_section])
        rows.append({"user": u, "done": n_done, "percent": round(n_done * 100 / total) if total else 0,
                     "last": d["last"], "sections": per_section})
    rows.sort(key=lambda r: (-r["percent"], r["user"].name.lower()))
    summary = {
        "people": len(rows),
        "started": sum(1 for r in rows if r["done"]),
        "completed": sum(1 for r in rows if total and r["done"] >= total),
        "avg": round(sum(r["percent"] for r in rows) / len(rows)) if rows else 0,
    }
    return render(request, "guides/manage/progress.html", {
        "guide": guide, "outline": outline, "rows": rows, "summary": summary,
        "can_edit": can_manage_content_for(request.user, guide.project),
        "page_title": f"Progress · {guide.title}",
        "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), (guide.title, _editor_url(guide)), ("Progress", "")],
    })


# ── Import / export / video detection ─────────────────────────────────────

@permission_required_code("content.manage")
def import_view(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    errors, result = [], None
    if request.method == "POST" and form.is_valid():
        try:
            data = load_json(form.cleaned_data["raw"])
            code = data.get("project_code") if isinstance(data, dict) else None
            project = Project.objects.filter(code__iexact=str(code).strip()).first() if code else None
            if code and project is not None and not can_manage_content_for(request.user, project):
                raise GuideImportError([f"project_code: you can only import guides for your own projects ({code!r} is not one of them)."])
            if not code and not can_manage_content_for(request.user, None):
                raise GuideImportError(["project_code: company-wide guides can only be imported by super admins and trainers — set a project_code."])
            existing = Guide.objects.filter(slug=str(data.get("slug") or "")).first() if isinstance(data, dict) else None
            if existing is not None and not can_manage_content_for(request.user, existing.project):
                raise GuideImportError([f"slug: the guide {existing.slug!r} belongs to a project you cannot manage."])
            result = import_guide(data, replace=form.cleaned_data["replace"], publish=form.cleaned_data["publish"],
                                  user=request.user, dry_run=form.cleaned_data["dry_run"])
        except GuideImportError as e:
            errors = e.errors
        else:
            if form.cleaned_data["dry_run"]:
                messages.info(request, f"Valid: {result.sections} sections and {result.steps} steps. Nothing was saved (dry run).")
            else:
                audit.log(request, "guide.import", result.guide, created=result.created, steps=result.steps)
                messages.success(request, f"Imported “{result.guide.title}”: {result.sections} sections, {result.steps} steps"
                                          + (f", {result.task_errors} Task Error examples" if result.task_errors else "")
                                          + (f" · progress kept on {result.steps_kept} existing steps" if result.steps_kept else "") + ".")
                for w in result.warnings[:10]:
                    messages.warning(request, w)
                return redirect("guides:manage_edit", pk=result.guide.pk)
    return render(request, "guides/manage/import.html", {
        "form": form, "errors": errors, "result": result, "schema": SCHEMA_HELP,
        "page_title": "Import a guide",
        "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), ("Import", "")],
    })


@permission_required_code("content.manage")
def doc_import(request):
    """Word / Markdown document (e.g. exported from Lark) → a new draft guide with the original English text."""
    from django.utils.text import slugify

    from .docimport import DocumentImportError, document_to_guide, outline_preview
    from .forms import DocumentImportForm

    form = DocumentImportForm(request.POST or None, request.FILES or None, projects=_projects_for(request.user))
    errors, preview = [], None
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        project = d.get("project")
        if not can_manage_content_for(request.user, project):
            form.add_error("project", "You can only create guides for your own projects." if project else
                           "Company-wide guides can only be created by super admins and trainers — choose a project.")
        else:
            f = d["file"]
            try:
                data = document_to_guide(f.read(), f.name, slug="tmp", title=d.get("title") or "", kind=d["kind"],
                                         project_code=project.code if project else None, source_url=d.get("source_url") or "")
                base = d.get("slug") or slugify(data["title_en"])[:100] or slugify(f.name.rsplit(".", 1)[0])[:100] or "guide"
                slug, n = base, 2
                while Guide.objects.filter(slug=slug).exists():
                    if d.get("slug"):
                        raise DocumentImportError(f"A guide with the address “{slug}” already exists — choose another one.")
                    slug, n = f"{base}-{n}", n + 1
                data["slug"] = slug
                if d.get("dry_run"):
                    preview = {"title": data["title"], "title_en": data["title_en"], "slug": slug, "outline": outline_preview(data)}
                else:
                    result = import_guide(data, user=request.user)
                    audit.log(request, "guide.document_import", result.guide, sections=result.sections, steps=result.steps)
                    messages.success(request, f"Imported {result.sections} sections and {result.steps} steps as a draft. "
                                              "Next: write the Bangla text of each step (the original English is shown next to it), "
                                              "set the video segments, add the Task Error examples and verify each item.")
                    return redirect("guides:manage_edit", pk=result.guide.pk)
            except (DocumentImportError, GuideImportError) as exc:
                errors = exc.errors if isinstance(exc, GuideImportError) else [str(exc)]
    return render(request, "guides/manage/doc_import.html", {
        "form": form, "errors": errors, "preview": preview,
        "page_title": "Import a document",
        "crumbs": [(ADMIN_LABEL, reverse("guides:manage")), ("Import a document", "")],
    })


@permission_required_code("content.manage")
def export(request, pk):
    guide = _guide_or_404(request, pk, edit=False)
    body = json.dumps(export_guide(guide), ensure_ascii=False, indent=2)
    resp = HttpResponse(body, content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{guide.slug}.json"'
    return resp


@permission_required_code("content.manage")
@require_GET
def video_info(request):
    url = request.GET.get("url", "").strip()
    info = embed_info(url, request.GET.get("start"), request.GET.get("end")) if url else None
    html = render_to_string("guides/_video.html", {"info": info, "title": "Preview", "caption": "", "compact": True}) if info else ""
    return JsonResponse({"ok": info is not None, "label": describe(info) if url else "", "info": info, "html": html})
