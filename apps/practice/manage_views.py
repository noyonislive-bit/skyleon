"""Admin side of the Practice Lab (/admin/practice/)."""

import json

from django.contrib import messages
from django.db.models import Avg, Count, Max, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.permissions import can_manage_content_for, has_permission, scoped_project_ids
from apps.backoffice.helpers import people_q, redirect_back
from apps.core import audit
from apps.core.choices import ContentStatus
from apps.projects.models import Project

from . import services
from .config import ACTION_LABELS, tool_config, save_tool_config
from .forms import PracticeTaskForm, ToolSettingsForm
from .models import AttemptStatus, PracticeAttempt, PracticeTask
from .scoring import clean_clips
from .views import result_context, workspace_payload


def _task_or_404(request, pk):
    task = services.manageable_tasks(request.user).filter(pk=pk).first()
    if task is None or not can_manage_content_for(request.user, task.project):
        raise Http404
    return task


def _projects_for(user):
    ids = scoped_project_ids(user)
    qs = Project.objects.order_by("name")
    return qs if ids is None else qs.filter(pk__in=ids)


@permission_required_code("content.manage")
def manage_list(request):
    user = request.user
    submitted = Q(attempts__status=AttemptStatus.SUBMITTED) & people_q(user, "attempts__user")
    tasks = services.manageable_tasks(user).annotate(
        n_attempts=Count("attempts", filter=submitted),
        n_people=Count("attempts__user", filter=submitted, distinct=True),
        avg_score=Avg("attempts__score", filter=submitted),
        n_passed=Count("attempts__user", filter=submitted & Q(attempts__passed=True), distinct=True),
    ).select_related("video__thumbnail")
    return render(request, "practice/manage/list.html", {
        "tasks": tasks, "can_settings": has_permission(request.user, "settings.manage"),
        "crumbs": [("Practice lab", "")],
        "page_title": "Practice lab",
        "page_subtitle": "Clipping exercises in a replica of the production tool, scored against your reference segmentation.",
    })


@permission_required_code("content.manage")
def task_form(request, pk=None):
    task = _task_or_404(request, pk) if pk else None
    form = PracticeTaskForm(request.POST or None, instance=task, user=request.user, projects=_projects_for(request.user))
    if request.method == "POST" and form.is_valid():
        if not can_manage_content_for(request.user, form.cleaned_data.get("project")):
            form.add_error("project", "You can only create practice tasks for your own projects.")
        else:
            obj = form.save(commit=False)
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            audit.log(request, "practice.save", obj)
            messages.success(request, "Practice task saved. Next: record the reference segmentation.")
            return redirect("practice:manage_edit", pk=obj.pk)
    return render(request, "practice/manage/form.html", {
        "form": form, "task": task,
        "attempt_count": task.attempts.filter(status=AttemptStatus.SUBMITTED).count() if task else 0,
        "page_title": f"Edit · {task.title}" if task else "New practice task",
        "crumbs": [("Practice lab", reverse("practice:manage")), (task.title if task else "New task", "")],
    })


@permission_required_code("content.manage")
@require_POST
def publish(request, pk):
    task = _task_or_404(request, pk)
    if request.POST.get("action") == "unpublish":
        task.status = ContentStatus.DRAFT
        messages.info(request, "Practice task moved back to draft.")
    else:
        if not task.video_id:
            messages.error(request, "Add a video before publishing.")
            return redirect("practice:manage_edit", pk=task.pk)
        task.status = ContentStatus.PUBLISHED
        task.published_at = task.published_at or timezone.now()
        if not task.reference_clips:
            messages.warning(request, "Published without a reference segmentation — employees will only be scored on coverage.")
        else:
            messages.success(request, "Practice task published.")
    task.save(update_fields=["status", "published_at", "updated_at"])
    audit.log(request, "practice.publish", task, status=task.status)
    return redirect_back(request, reverse("practice:manage"))


@permission_required_code("content.manage")
@require_POST
def delete(request, pk):
    task = _task_or_404(request, pk)
    if task.attempts.filter(status=AttemptStatus.SUBMITTED).exists():
        messages.error(request, "Employees have submitted this task — unpublish it instead of deleting, so their results are kept.")
        return redirect("practice:manage_edit", pk=task.pk)
    audit.log(request, "practice.delete", task, title=task.title)
    task.delete()
    messages.success(request, "Practice task deleted.")
    return redirect("practice:manage")


@permission_required_code("content.manage")
def reference_editor(request, pk):
    task = _task_or_404(request, pk)
    if not task.video_id:
        messages.error(request, "Add a video first.")
        return redirect("practice:manage_edit", pk=task.pk)
    tasks = list(services.manageable_tasks(request.user))
    prev_task, next_task = services.neighbours(task, tasks)
    urls = {
        "save": "",
        "submit": reverse("practice:manage_reference_save", args=[task.pk]),
        "taskError": "",
        "back": reverse("practice:manage_edit", args=[task.pk]),
        "prev": reverse("practice:manage_reference", args=[prev_task.pk]) if prev_task and prev_task.video_id else "",
        "next": reverse("practice:manage_reference", args=[next_task.pk]) if next_task and next_task.video_id else "",
    }
    payload = workspace_payload(request, task, mode="reference", clips=task.reference_clips, urls=urls)
    return render(request, "practice/workspace.html", {
        "task": task, "payload": payload, "mode": "reference", "back_url": urls["back"], "show_intro": False,
    })


@permission_required_code("content.manage")
@require_POST
def reference_save(request, pk):
    task = _task_or_404(request, pk)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = None
    clips = data.get("clips") if isinstance(data, dict) else None
    if not isinstance(clips, list):  # never wipe the reference because of a malformed request
        return JsonResponse({"ok": False, "error": "clips must be a list of [start, end] pairs."}, status=400)
    lo, hi = services.task_range(task)
    task.reference_clips = [list(c) for c in clean_clips(clips, lo, hi)]
    task.save(update_fields=["reference_clips", "updated_at"])
    audit.log(request, "practice.reference", task, clips=len(task.reference_clips))
    return JsonResponse({"ok": True, "reference": True, "clips": task.reference_clips,
                         "resultUrl": reverse("practice:manage_edit", args=[task.pk])})


@permission_required_code("content.manage")
def results(request, pk):
    task = _task_or_404(request, pk)
    in_scope = people_q(request.user)
    attempts = (
        PracticeAttempt.objects.filter(in_scope, task=task, status=AttemptStatus.SUBMITTED)
        .select_related("user").order_by("user__name", "-submitted_at")
    )
    people = {}
    for a in attempts:
        row = people.setdefault(a.user_id, {"user": a.user, "attempts": 0, "best": None, "last": None, "passed": False, "latest": a, "task_error": None})
        row["attempts"] += 1
        row["best"] = a.score if row["best"] is None or (a.score or 0) > row["best"] else row["best"]
        row["last"] = max(filter(None, [row["last"], a.submitted_at]))
        row["passed"] = row["passed"] or bool(a.passed)
        if a.task_error and not row["task_error"]:
            row["task_error"] = a.task_error
    errors = PracticeAttempt.objects.filter(in_scope, task=task).exclude(task_error={}).select_related("user").order_by("-updated_at")[:20]
    return render(request, "practice/manage/results.html", {
        "task": task, "people": sorted(people.values(), key=lambda r: r["user"].name), "errors": errors,
        "page_title": f"Results · {task.title}",
        "crumbs": [("Practice lab", reverse("practice:manage")), (task.title, reverse("practice:manage_edit", args=[task.pk])), ("Results", "")],
    })


@permission_required_code("content.manage")
def attempt_detail(request, attempt_id):
    attempt = get_object_or_404(PracticeAttempt.objects.select_related("task", "user"), pk=attempt_id, status=AttemptStatus.SUBMITTED)
    _task_or_404(request, attempt.task_id)
    if not PracticeAttempt.objects.filter(people_q(request.user), pk=attempt.pk).exists():
        raise Http404
    ctx = result_context(attempt, back_url=reverse("practice:manage_results", args=[attempt.task_id]))
    ctx["staff_view"] = True
    ctx["page_title"] = f"{attempt.user.name} · {attempt.task.title}"
    ctx["crumbs"] = [("Practice lab", reverse("practice:manage")), (attempt.task.title, reverse("practice:manage_results", args=[attempt.task_id])), (attempt.user.name, "")]
    return render(request, "practice/manage/attempt.html", ctx)


@permission_required_code("settings.manage")
def tool_settings(request):
    form = ToolSettingsForm(request.POST or None, config=tool_config())
    if request.method == "POST" and form.is_valid():
        save_tool_config(form.to_config())
        audit.log(request, "practice.tool_settings")
        messages.success(request, "Tool settings saved.")
        return redirect("practice:manage_settings")
    shortcut_fields = [form[f"key_{a}"] for a in ACTION_LABELS]
    return render(request, "practice/manage/settings.html", {
        "form": form, "shortcut_fields": shortcut_fields, "page_title": "Practice tool settings",
        "page_subtitle": "Match the practice tool to the production tool: N-key behaviour, speeds and keyboard shortcuts.",
        "crumbs": [("Practice lab", reverse("practice:manage")), ("Tool settings", "")],
    })
