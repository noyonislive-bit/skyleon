"""Employee side of the Practice Lab (/portal/practice/)."""

import json

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.views.decorators.http import require_POST

from apps.accounts.decorators import employee_required
from apps.storage.services import media_url

from . import services
from .config import ACTION_LABELS, ACTION_LABELS_BN, tool_config
from .models import AttemptPhase, AttemptStatus, PracticeAttempt, PracticeTask
from .scoring import clean_clips, clip_matches


def _json_body(request) -> dict:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _visible_task_or_404(request, pk):
    task = services.visible_tasks(request.user).filter(pk=pk).first()
    if task is None:
        raise Http404
    return task


def workspace_payload(request, task, *, mode, clips, urls, guide=None, extra=None):
    """mode: practice (instant score) · review (weekly review, own work) · correct (fix own work with the
    reviewer's answer shown as a guide track) · reference (admin: trainer reference / reviewer answer)."""
    lo, hi = services.task_range(task)
    video_url = media_url(task.video, request.user) if task.video_id else ""
    bangla = translation.get_language() == "bn"
    return {
        "mode": mode,
        "task": {"id": task.pk, "title": task.title, "rangeStart": lo, "rangeEnd": hi,
                 "duration": task.video.duration_sec if task.video_id else None},
        "video": {"url": video_url, "hls": bool(task.video_id and task.video.is_hls)},
        "clips": clips,
        "config": tool_config(),
        "labels": ACTION_LABELS_BN if bangla else ACTION_LABELS,
        "lang": "bn" if bangla else "en",
        "urls": urls,
        "guide": guide or [],
        **(extra or {}),
    }


@employee_required
def task_list(request):
    tasks = list(services.visible_tasks(request.user))
    reviews = [{"task": t, **services.review_state(t, request.user)} for t in tasks if t.is_review]
    tasks = [t for t in tasks if not t.is_review]
    summary = services.user_summary(request.user, tasks)
    rows = [{"task": t, **summary[t.pk]} for t in tasks]
    recent = (
        PracticeAttempt.objects.filter(user=request.user, status=AttemptStatus.SUBMITTED, score__isnull=False)
        .select_related("task")
        .order_by("-submitted_at")[:8]
    )
    return render(request, "practice/list.html", {
        "rows": rows, "reviews": sorted(reviews, key=lambda r: r["task"].published_at or r["task"].created_at, reverse=True), "recent": recent, "page_title": "প্র্যাকটিস ল্যাব", "crumbs": [{"label": "প্র্যাকটিস ল্যাব", "url": ""}],
        "page_subtitle": "আসল কাজের টুলের হুবহু কপিতে ক্লিপিং প্র্যাকটিস করুন। আপনার ক্লিপগুলো ট্রেইনারের রেফারেন্সের সাথে মিলিয়ে স্কোর দেওয়া হয়।",
    })


@employee_required
def workspace(request, pk):
    task = _visible_task_or_404(request, pk)
    if task.is_review and not services.own_work_open(task, services.first_attempt(task, request.user, create=False)):
        return redirect("practice:review", pk=task.pk)  # answer is out and own work submitted → compare
    draft = services.get_draft(task, request.user)
    prev_task, next_task = services.neighbours(task, services.visible_tasks(request.user))
    urls = {
        "save": reverse("practice:save", args=[task.pk]),
        "submit": reverse("practice:submit", args=[task.pk]),
        "taskError": reverse("practice:task_error", args=[task.pk]),
        "back": reverse("practice:list"),
        "prev": reverse("practice:workspace", args=[prev_task.pk]) if prev_task else "",
        "next": reverse("practice:workspace", args=[next_task.pk]) if next_task else "",
    }
    mode = "review" if task.is_review else "practice"
    extra = {}
    if task.is_review:
        urls["review"] = reverse("practice:review", args=[task.pk])
        extra = {"review": {"submitted": draft.status == AttemptStatus.SUBMITTED, "answer": task.answer_published,
                            "due": timezone.localtime(task.due_at).strftime("%d/%m %I:%M %p") if task.due_at else ""}}
    payload = workspace_payload(request, task, mode=mode, clips=draft.clips, urls=urls, extra=extra)
    attempts = PracticeAttempt.objects.filter(task=task, user=request.user, status=AttemptStatus.SUBMITTED).count()
    return render(request, "practice/workspace.html", {
        "task": task, "payload": payload, "mode": mode, "attempt_count": attempts,
        "show_intro": not draft.clips and attempts == 0, "back_url": urls["back"],
        "submitted_once": draft.status == AttemptStatus.SUBMITTED,
    })


def _review_task_or_404(request, pk):
    task = _visible_task_or_404(request, pk)
    if not task.is_review:
        raise Http404
    return task


@employee_required
def correct(request, pk):
    """Weekly review: fix your own work with the reviewer's answer shown under the timeline."""
    task = _review_task_or_404(request, pk)
    first = services.first_attempt(task, request.user, create=False)
    if services.own_work_open(task, first):
        if task.answer_published:
            messages.info(request, "আগে নিজে ক্লিপ করে জমা দিন — তারপর রিভিউয়ারের উত্তর দেখতে পারবেন।")
        return redirect("practice:workspace", pk=task.pk)
    draft = services.correction_draft(task, request.user)
    lo, hi = services.task_range(task)
    urls = {
        "save": reverse("practice:correct_save", args=[task.pk]),
        "submit": reverse("practice:correct_submit", args=[task.pk]),
        "taskError": "",
        "back": reverse("practice:review", args=[task.pk]),
        "review": reverse("practice:review", args=[task.pk]),
        "prev": "", "next": "",
    }
    payload = workspace_payload(request, task, mode="correct", clips=draft.clips, urls=urls,
                                guide=[list(c) for c in clean_clips(task.reference_clips, lo, hi)],
                                extra={"review": {"firstScore": first.score, "answer": True}})
    return render(request, "practice/workspace.html", {
        "task": task, "payload": payload, "mode": "correct", "back_url": urls["back"], "show_intro": not services.corrections(task, request.user).exists(),
        "attempt_count": services.corrections(task, request.user).count(),
    })


@employee_required
@require_POST
def correct_save(request, pk):
    task = _review_task_or_404(request, pk)
    if services.own_work_open(task, services.first_attempt(task, request.user, create=False)):
        return JsonResponse({"ok": False, "error": "not available"}, status=409)
    data = _json_body(request)
    draft = services.save_draft(services.correction_draft(task, request.user), data.get("clips"), data.get("timeSpent"))
    return JsonResponse({"ok": True, "clips": draft.clips, "savedAt": timezone.now().isoformat()})


@employee_required
@require_POST
def correct_submit(request, pk):
    task = _review_task_or_404(request, pk)
    first = services.first_attempt(task, request.user, create=False)
    if services.own_work_open(task, first):
        return JsonResponse({"ok": False, "error": "not available"}, status=409)
    data = _json_body(request)
    attempt = services.submit(services.correction_draft(task, request.user), data.get("clips"), data.get("timeSpent"))
    return JsonResponse({
        "ok": True, "score": attempt.score, "passed": attempt.passed, "passingScore": task.passing_score,
        "metrics": attempt.metrics, "firstScore": first.score, "phase": "correction",
        "resultUrl": reverse("practice:review", args=[task.pk]),
    })


@employee_required
def review(request, pk):
    """Weekly review: my clips next to the reviewer's answer, the match %, every answer clip checked."""
    task = _review_task_or_404(request, pk)
    st = services.review_state(task, request.user)
    if st["state"] in ("todo", "waiting"):
        return redirect("practice:workspace", pk=task.pk)
    first = st["first"]
    latest = st["corrections"][-1] if st["corrections"] else None
    ctx = result_context(first, back_url=reverse("practice:list"))
    lo, hi = services.task_range(task)
    ref = clean_clips(task.reference_clips, lo, hi)
    span = max(hi - lo, 0.001)

    def bars(clips):
        return [{"left": (a - lo) / span * 100, "width": max(0.3, (b - a) / span * 100), "start": a, "end": b, "n": i}
                for i, (a, b) in enumerate(clips, start=1)]

    rows = [
        {"label": "আমার কাজ", "bars": bars([tuple(c) for c in first.clips]), "css": "bg-sky-500/80"},
        {"label": "রিভিউয়ারের উত্তর", "bars": bars(ref), "css": "bg-emerald-600/80"},
    ]
    if latest:
        rows.append({"label": "সংশোধনের পর", "bars": bars([tuple(c) for c in latest.clips]), "css": "bg-violet-500/80"})
    matches = clip_matches([tuple(c) for c in first.clips], ref, task.tolerance_sec)
    if latest:
        for m, after in zip(matches, clip_matches([tuple(c) for c in latest.clips], ref, task.tolerance_sec)):
            m["after"] = after["status"]
    ctx.update({
        "st": st, "latest": latest, "comparison_rows": rows, "matches": matches,
        "improvement": round(latest.score - first.score) if latest and latest.score is not None and first.score is not None else None,
        "page_title": f"রিভিউ · {task.title}",
        "crumbs": [{"label": "প্র্যাকটিস ল্যাব", "url": reverse("practice:list")}, {"label": task.title, "url": ""}],
    })
    return render(request, "practice/review.html", ctx)


@employee_required
@require_POST
def save(request, pk):
    task = _visible_task_or_404(request, pk)
    if task.is_review and not services.own_work_open(task, services.first_attempt(task, request.user, create=False)):
        return JsonResponse({"ok": False, "error": "The answer is out — your own work is final."}, status=409)
    data = _json_body(request)
    draft = services.save_draft(services.get_draft(task, request.user), data.get("clips"), data.get("timeSpent"))
    return JsonResponse({"ok": True, "clips": draft.clips, "savedAt": timezone.now().isoformat()})


@employee_required
@require_POST
def submit(request, pk):
    task = _visible_task_or_404(request, pk)
    if task.is_review and not services.own_work_open(task, services.first_attempt(task, request.user, create=False)):
        return JsonResponse({"ok": False, "error": "The answer is out — your own work is final."}, status=409)
    data = _json_body(request)
    attempt = services.submit(services.get_draft(task, request.user), data.get("clips"), data.get("timeSpent"))
    if task.is_review:
        return JsonResponse({
            "ok": True, "pending": attempt.score is None, "score": attempt.score, "passed": attempt.passed,
            "passingScore": task.passing_score, "metrics": attempt.metrics, "phase": "first",
            "resultUrl": reverse("practice:review", args=[task.pk]) if attempt.score is not None else "",
        })
    return JsonResponse({
        "ok": True,
        "score": attempt.score,
        "passed": attempt.passed,
        "passingScore": task.passing_score,
        "metrics": attempt.metrics,
        "resultUrl": reverse("practice:result", args=[attempt.pk]),
    })


@employee_required
@require_POST
def task_error(request, pk):
    task = _visible_task_or_404(request, pk)
    data = _json_body(request)
    draft = services.get_draft(task, request.user)
    draft.task_error = {
        "reason": str(data.get("reason") or "")[:100],
        "comment": str(data.get("comment") or "")[:1000],
        "at": timezone.now().isoformat(),
    }
    draft.save(update_fields=["task_error", "updated_at"])
    return JsonResponse({"ok": True})


@employee_required
def result(request, attempt_id):
    attempt = get_object_or_404(PracticeAttempt.objects.select_related("task", "task__project"), pk=attempt_id)
    if attempt.user_id != request.user.pk:
        raise Http404
    if attempt.status != AttemptStatus.SUBMITTED or attempt.score is None:
        return redirect("practice:workspace", pk=attempt.task_id)
    if attempt.task.is_review:
        return redirect("practice:review", pk=attempt.task_id)
    ctx = result_context(attempt, back_url=reverse("practice:list"))
    ctx["crumbs"] = [{"label": "প্র্যাকটিস ল্যাব", "url": reverse("practice:list")}, {"label": "ফলাফল", "url": ""}]
    return render(request, "practice/result.html", ctx)


def result_context(attempt, *, back_url):
    """Shared by the employee result page (Bangla) and the admin attempt view (English)."""
    task = attempt.task
    bn = translation.get_language() == "bn"
    lo, hi = services.task_range(task)
    span = max(hi - lo, 0.001)
    ref = clean_clips(task.reference_clips, lo, hi)

    def bars(clips):
        return [{"left": (s - lo) / span * 100, "width": max(0.3, (e - s) / span * 100), "start": s, "end": e, "n": i}
                for i, (s, e) in enumerate(clips, start=1)]

    ticks = []
    step = next((s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300) if span / s <= 12), 600)
    t = (int(lo // step) + 1) * step
    while t < hi:
        ticks.append({"left": (t - lo) / span * 100, "label": f"{int(t // 60):02d}:{int(t % 60):02d}"})
        t += step
    return {
        "attempt": attempt, "task": task, "metrics": attempt.metrics or {},
        "user_bars": bars([tuple(c) for c in attempt.clips]), "ref_bars": bars(ref),
        "gap_bars": bars([tuple(g) for g in (attempt.metrics or {}).get("uncovered", [])]),
        "ticks": ticks, "range_label": f"{int(lo // 60):02d}:{int(lo % 60):02d} – {int(hi // 60):02d}:{int(hi % 60):02d}",
        "comparison_rows": [
            {"label": "আপনার ক্লিপ" if bn else "Your clips", "bars": bars([tuple(c) for c in attempt.clips]), "css": "bg-brand-500/80"},
            {"label": ("রিভিউয়ারের উত্তর" if bn else "Reviewer's answer") if task.is_review else ("রেফারেন্স" if bn else "Reference"),
             "bars": bars(ref), "css": "bg-emerald-500/80"},
            {"label": "বাদ পড়া অংশ" if bn else "Uncovered", "bars": bars([tuple(g) for g in (attempt.metrics or {}).get("uncovered", [])]), "css": "bg-amber-400/80"},
        ],
        "back_url": back_url,
        "page_title": f"{'ফলাফল' if bn else 'Result'} · {task.title}",
    }
