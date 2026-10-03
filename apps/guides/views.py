"""Employee side of the work guides (/portal/guides/)."""

import json

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.decorators import employee_required
from apps.accounts.permissions import has_permission

from . import services
from .models import GuideStep

LIST_TITLE = "কাজের গাইড"


def _crumbs(*items):
    return [{"label": label, "url": url} for label, url in items]


@employee_required
def guide_list(request):
    guides = list(services.visible_guides(request.user))
    stats = services.guide_stats(guides, request.user)
    rows = []
    for g in guides:
        st = stats[g.pk]
        anchor = st["first_unread"] or st["first"]
        rows.append({"guide": g, **st,
                     "resume_url": g.get_absolute_url() + (f"#{anchor}" if st["first_unread"] and st["done"] else ""),
                     "step_url": reverse("guides:step", args=[g.slug, anchor]) if anchor else ""})
    total_steps = sum(r["total"] for r in rows)
    done_steps = sum(r["done"] for r in rows)
    return render(request, "guides/list.html", {
        "rows": rows,
        "total_steps": total_steps,
        "done_steps": done_steps,
        "can_manage": has_permission(request.user, "content.manage"),
        "page_title": LIST_TITLE,
        "page_subtitle": "কাজের নিয়ম, ধাপে ধাপে নির্দেশনা আর মূল ভিডিও — সব এক জায়গায়। প্রতিটি ধাপ পড়ে “বুঝেছি” চাপুন।",
        "crumbs": _crumbs((LIST_TITLE, "")),
    })


def _guide_or_404(request, slug):
    guide, preview = services.readable_guide(request.user, slug)
    if guide is None:
        raise Http404
    return guide, preview


def _reader_context(request, guide, preview, outline):
    staff = has_permission(request.user, "content.manage")
    return {
        "guide": guide,
        "outline": outline,
        "is_preview": preview,
        "is_staff": staff,
        "can_edit": staff and services.can_edit(request.user, guide),
        "list_url": reverse("guides:list"),
    }


@employee_required
def detail(request, slug):
    guide, preview = _guide_or_404(request, slug)
    outline = services.build_outline(guide, request.user)
    target = request.GET.get("step") or ""
    if target and not (outline.step(target) or outline.section(target)):
        target = ""
    first = outline.first_unread or (outline.steps[0] if outline.steps else None)
    ctx = _reader_context(request, guide, preview, outline)
    ctx.update({
        "target": target,
        "step_mode_url": reverse("guides:step", args=[guide.slug, first.anchor]) if first else "",
        "crumbs": _crumbs((LIST_TITLE, reverse("guides:list")), (guide.title, "")),
        "page_title": guide.title,
    })
    return render(request, "guides/detail.html", ctx)


@employee_required
def step(request, slug, anchor):
    guide, preview = _guide_or_404(request, slug)
    outline = services.build_outline(guide, request.user)
    node = outline.step(anchor)
    if node is None:
        section = outline.section(anchor)
        if section is not None and section.steps:
            return redirect("guides:step", slug=guide.slug, anchor=section.steps[0].anchor)
        raise Http404
    ctx = _reader_context(request, guide, preview, outline)
    ctx.update({
        "node": node,
        "section": node.section,
        "show_section_intro": node.section.steps and node.section.steps[0] is node,
        "doc_url": f"{guide.get_absolute_url()}#{node.anchor}",
        "crumbs": _crumbs((LIST_TITLE, reverse("guides:list")), (guide.title, guide.get_absolute_url()),
                          (node.section.obj.title, f"{guide.get_absolute_url()}#{node.section.anchor}"), (node.obj.title, "")),
        "page_title": node.obj.title,
    })
    return render(request, "guides/step.html", ctx)


def _wants_json(request):
    return (request.content_type == "application/json"
            or "application/json" in request.headers.get("Accept", ""))


@employee_required
@require_POST
def toggle_done(request, pk):
    step = get_object_or_404(GuideStep.objects.select_related("guide", "guide__project", "section"), pk=pk)
    guide, _ = services.readable_guide(request.user, step.guide.slug)
    if guide is None:
        raise Http404
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
    else:
        data = request.POST
    raw = data.get("done")
    if raw is None or raw == "":
        done = not step.progress.filter(user=request.user).exists()
    else:
        done = raw is True or str(raw).lower() in ("1", "true", "yes", "on")
    services.set_done(request.user, step, done)
    payload = services.progress_payload(request.user, step)
    if _wants_json(request):
        return JsonResponse(payload)
    nxt = str(data.get("next") or "")
    if not nxt or not nxt.startswith("/") or nxt.startswith("//") or not url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = f"{step.guide.get_absolute_url()}#{step.anchor}"
    return redirect(nxt)
