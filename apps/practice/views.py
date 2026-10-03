"""Employee side of the Practice Lab (/portal/practice/)."""

import json

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import employee_required
from apps.storage.services import media_url

from . import services
from .config import ACTION_LABELS, tool_config
from .models import AttemptStatus, PracticeAttempt, PracticeTask
from .scoring import clean_clips


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _visible_task_or_404(request, pk):
    task = services.visible_tasks(request.user).filter(pk=pk).first()
    if task is None:
        raise Http404
    return task


def workspace_payload(request, task, *, mode, clips, urls):
    lo, hi = services.task_range(task)
    video_url = media_url(task.video, request.user) if task.video_id else ""
    return {
        "mode": mode,
        "task": {"id": task.pk, "title": task.title, "rangeStart": lo, "rangeEnd": hi,
                 "duration": task.video.duration_sec if task.video_id else None},
        "video": {"url": video_url, "hls": bool(task.video_id and task.video.is_hls)},
        "clips": clips,
        "config": tool_config(),
        "labels": ACTION_LABELS,
        "urls": urls,
    }


@employee_required
def task_list(request):
    tasks = list(services.visible_tasks(request.user))
    summary = services.user_summary(request.user, tasks)
    rows = [{"task": t, **summary[t.pk]} for t in tasks]
    recent = (
        PracticeAttempt.objects.filter(user=request.user, status=AttemptStatus.SUBMITTED)
        .select_related("task")
        .order_by("-submitted_at")[:8]
    )
    return render(request, "practice/list.html", {
        "rows": rows, "recent": recent, "page_title": "Practice Lab", "crumbs": [{"label": "Practice Lab", "url": ""}],
        "page_subtitle": "Practise clipping in an exact replica of the production tool. Your clips are scored against the trainer's reference.",
    })


@employee_required
def workspace(request, pk):
    task = _visible_task_or_404(request, pk)
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
    payload = workspace_payload(request, task, mode="practice", clips=draft.clips, urls=urls)
    attempts = PracticeAttempt.objects.filter(task=task, user=request.user, status=AttemptStatus.SUBMITTED).count()
    return render(request, "practice/workspace.html", {
        "task": task, "payload": payload, "mode": "practice", "attempt_count": attempts,
        "show_intro": not draft.clips and attempts == 0, "back_url": urls["back"],
    })


@employee_required
@require_POST
def save(request, pk):
    task = _visible_task_or_404(request, pk)
    data = _json_body(request)
    draft = services.save_draft(services.get_draft(task, request.user), data.get("clips"), data.get("timeSpent"))
    return JsonResponse({"ok": True, "clips": draft.clips, "savedAt": timezone.now().isoformat()})


@employee_required
@require_POST
def submit(request, pk):
    task = _visible_task_or_404(request, pk)
    data = _json_body(request)
    attempt = services.submit(services.get_draft(task, request.user), data.get("clips"), data.get("timeSpent"))
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
    if attempt.status != AttemptStatus.SUBMITTED:
        return redirect("practice:workspace", pk=attempt.task_id)
    ctx = result_context(attempt, back_url=reverse("practice:list"))
    ctx["crumbs"] = [{"label": "Practice Lab", "url": reverse("practice:list")}, {"label": "Result", "url": ""}]
    return render(request, "practice/result.html", ctx)


def result_context(attempt, *, back_url):
    task = attempt.task
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
            {"label": "Your clips", "bars": bars([tuple(c) for c in attempt.clips]), "css": "bg-brand-500/80"},
            {"label": "Reference", "bars": bars(ref), "css": "bg-emerald-500/80"},
            {"label": "Uncovered", "bars": bars([tuple(g) for g in (attempt.metrics or {}).get("uncovered", [])]), "css": "bg-amber-400/80"},
        ],
        "back_url": back_url,
        "page_title": f"Result · {task.title}",
    }
