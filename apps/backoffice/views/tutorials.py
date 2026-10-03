from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.permissions import can_manage_content_for, project_scope
from apps.core import audit
from apps.core.choices import ContentStatus, ProgressStatus
from apps.training.models import Cadence, Tutorial, TutorialCategory, TutorialProgress
from apps.training.services import assign_tutorial, publish_tutorial

from ..forms import AssignPeopleForm, CategoryForm, TutorialForm
from ..helpers import (
    assignable_employees,
    can_edit_content,
    day_end,
    employee_scope,
    get_content,
    paginate,
    pct,
    people_q,
    redirect_back,
    staff_projects,
)


@permission_required_code("content.manage")
def tutorial_list(request):
    user = request.user
    qs = project_scope(Tutorial.objects.all(), user).select_related("project", "category", "video__thumbnail", "created_by")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "project", "category", "status", "cadence")}
    if f["q"]:
        qs = qs.filter(Q(title__icontains=f["q"]) | Q(description__icontains=f["q"]))
    if f["project"] == "global":
        qs = qs.filter(project__isnull=True)
    elif f["project"].isdigit():
        qs = qs.filter(project_id=int(f["project"]))
    if f["category"].isdigit():
        qs = qs.filter(category_id=int(f["category"]))
    if f["status"] in ContentStatus.values:
        qs = qs.filter(status=f["status"])
    if f["cadence"] in Cadence.values:
        qs = qs.filter(cadence=f["cadence"])
    people = people_q(user, "progress__user")  # same people as the tutorial's tracking page
    qs = qs.annotate(
        assigned=Count("progress", filter=people & Q(progress__assigned=True)),
        completed=Count("progress", filter=people & Q(progress__assigned=True, progress__status=ProgressStatus.COMPLETED)),
        viewers=Count("progress", filter=people & Q(progress__first_viewed_at__isnull=False)),
    ).order_by("-created_at")
    page = paginate(request, qs)
    for t in page:
        t.completion = pct(t.completed, t.assigned)
        t.can_edit = can_edit_content(user, t.project_id)
    return render(request, "backoffice/tutorials/list.html", {
        "page_title": "Tutorials",
        "page_subtitle": "Training videos — onboarding, daily and weekly training, reference material.",
        "crumbs": [("Tutorials", None)],
        "page": page,
        "projects": staff_projects(user).order_by("name"),
        "categories": TutorialCategory.objects.all(),
        "statuses": ContentStatus.choices,
        "cadences": Cadence.choices,
        "filters": f,
    })


def _tutorial_form(request, tutorial=None):
    initial = {}
    if tutorial is None and request.GET.get("project", "").isdigit():
        initial["project"] = int(request.GET["project"])
    form = TutorialForm(request.POST or None, instance=tutorial, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if tutorial is None:
            obj.created_by = request.user
        obj.save()
        audit.log(request, "tutorial.edit" if tutorial else "tutorial.create", obj)
        action = request.POST.get("then")
        if action == "publish" and obj.status != ContentStatus.PUBLISHED:
            if not obj.video_id:
                messages.warning(request, "Saved as draft — add a video before publishing.")
            else:
                n = publish_tutorial(obj)
                audit.log(request, "tutorial.publish", obj, assigned=n)
                messages.success(request, f"“{obj.title}” is published" + (f" and assigned to {n} employee(s)." if n else "."))
                return redirect("backoffice:tutorial_detail", pk=obj.pk)
        messages.success(request, "Tutorial saved.")
        return redirect("backoffice:tutorial_detail", pk=obj.pk)
    crumbs = [("Tutorials", reverse("backoffice:tutorial_list"))]
    if tutorial:
        crumbs += [(tutorial.title, reverse("backoffice:tutorial_detail", args=[tutorial.pk])), ("Edit", None)]
    else:
        crumbs += [("New tutorial", None)]
    return render(request, "backoffice/tutorials/form.html", {
        "page_title": "Edit tutorial" if tutorial else "New tutorial",
        "page_subtitle": "Upload the video, describe it and choose who should watch it.",
        "crumbs": crumbs,
        "form": form,
        "tutorial": tutorial,
    })


@permission_required_code("content.manage")
def tutorial_create(request):
    return _tutorial_form(request)


@permission_required_code("content.manage")
def tutorial_edit(request, pk):
    return _tutorial_form(request, get_content(request, Tutorial, pk, manage=True, select=("video__thumbnail",)))


@permission_required_code("content.manage")
def tutorial_detail(request, pk):
    user = request.user
    tutorial = get_content(request, Tutorial, pk, select=("project", "category", "video__thumbnail", "created_by"))
    can_edit = can_manage_content_for(user, tutorial.project)
    rows = (TutorialProgress.objects.filter(tutorial=tutorial, user__in=employee_scope(user))
            .select_related("user").order_by("status", "user__name"))
    summary = rows.aggregate(
        total=Count("pk"), assigned=Count("pk", filter=Q(assigned=True)),
        completed=Count("pk", filter=Q(status=ProgressStatus.COMPLETED)),
        in_progress=Count("pk", filter=Q(status=ProgressStatus.IN_PROGRESS)),
        not_started=Count("pk", filter=Q(status=ProgressStatus.NOT_STARTED)),
    )
    f = {k: request.GET.get(k, "").strip() for k in ("q", "status", "team", "member")}
    if f["q"]:
        rows = rows.filter(Q(user__name__icontains=f["q"]) | Q(user__email__icontains=f["q"]) | Q(user__employee_id__icontains=f["q"]))
    if f["status"] == "watched":
        rows = rows.filter(status=ProgressStatus.COMPLETED)
    elif f["status"] == "not_watched":
        rows = rows.exclude(status=ProgressStatus.COMPLETED)
    elif f["status"] in ProgressStatus.values:
        rows = rows.filter(status=f["status"])
    teams = []
    if tutorial.project_id:
        teams = list(tutorial.project.teams.all())
        if f["member"] == "members":
            rows = rows.filter(user__memberships__project=tutorial.project)
        elif f["member"] == "others":
            rows = rows.exclude(user__memberships__project=tutorial.project)
        if f["team"].isdigit():
            rows = rows.filter(user__memberships__project=tutorial.project, user__memberships__team_id=int(f["team"]))
    page = paginate(request, rows, 50)
    assign_form = None
    if can_edit and tutorial.is_published:
        candidates = assignable_employees(user).exclude(
            pk__in=TutorialProgress.objects.filter(tutorial=tutorial, assigned=True).values("user_id"))
        if tutorial.project_id:
            candidates = candidates.filter(memberships__project=tutorial.project)
        assign_form = AssignPeopleForm(user=user, queryset=candidates)
    return render(request, "backoffice/tutorials/detail.html", {
        "page_title": None,
        "crumbs": [("Tutorials", reverse("backoffice:tutorial_list")), (tutorial.title, None)],
        "tutorial": tutorial,
        "can_edit": can_edit,
        "page": page,
        "summary": summary,
        "completion": pct(summary["completed"], summary["assigned"]),
        "filters": f,
        "teams": teams,
        "assign_form": assign_form,
        "threshold": settings.VIDEO_COMPLETION_THRESHOLD,
    })


@require_POST
@permission_required_code("content.manage")
def tutorial_status(request, pk):
    tutorial = get_content(request, Tutorial, pk, manage=True)
    action = request.POST.get("action")
    if action == "publish":
        if not tutorial.video_id:
            messages.error(request, "Add a video before publishing.")
        else:
            n = publish_tutorial(tutorial)
            audit.log(request, "tutorial.publish", tutorial, assigned=n)
            messages.success(request, f"Published" + (f" and assigned to {n} employee(s) — they have been notified." if n else "."))
    elif action in ("unpublish", "archive"):
        tutorial.status = ContentStatus.DRAFT if action == "unpublish" else ContentStatus.ARCHIVED
        tutorial.save(update_fields=["status", "updated_at"])
        audit.log(request, f"tutorial.{action}", tutorial)
        messages.success(request, "Tutorial moved back to draft." if action == "unpublish" else "Tutorial archived. Progress history is kept.")
    return redirect_back(request, reverse("backoffice:tutorial_detail", args=[tutorial.pk]))


@require_POST
@permission_required_code("content.manage")
def tutorial_assign(request, pk):
    tutorial = get_content(request, Tutorial, pk, manage=True)
    if not tutorial.is_published:
        messages.error(request, "Publish the tutorial before assigning it.")
        return redirect("backoffice:tutorial_detail", pk=tutorial.pk)
    qs = assignable_employees(request.user)
    if tutorial.project_id:
        qs = qs.filter(memberships__project=tutorial.project)
    form = AssignPeopleForm(request.POST, user=request.user, queryset=qs)
    if form.is_valid():
        users = list(form.cleaned_data["users"])
        n = assign_tutorial(tutorial, users, due_at=day_end(form.cleaned_data["due_date"]))
        audit.log(request, "tutorial.assign", tutorial, users=[u.pk for u in users])
        messages.success(request, f"Assigned to {n} employee(s)." if n else "Those employees already had this tutorial.")
    else:
        messages.error(request, "Select at least one employee.")
    return redirect("backoffice:tutorial_detail", pk=tutorial.pk)


@require_POST
@permission_required_code("content.manage")
def tutorial_delete(request, pk):
    tutorial = get_content(request, Tutorial, pk, manage=True)
    if tutorial.status == ContentStatus.PUBLISHED:
        messages.error(request, "Unpublish or archive the tutorial before deleting it.")
        return redirect("backoffice:tutorial_detail", pk=tutorial.pk)
    audit.log(request, "tutorial.delete", tutorial, title=tutorial.title)
    tutorial.delete()
    messages.success(request, "Tutorial deleted.")
    return redirect("backoffice:tutorial_list")


# ── Categories ──────────────────────────────────────────────────────────────

@permission_required_code("content.manage")
def category_list(request):
    can_edit = can_manage_content_for(request.user, None)
    form = CategoryForm(request.POST or None, initial={"order": TutorialCategory.objects.count()})
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if form.is_valid():
            cat = form.save()
            audit.log(request, "category.create", cat)
            messages.success(request, f"Category “{cat.name}” added.")
            return redirect("backoffice:category_list")
    categories = list(TutorialCategory.objects.annotate(n=Count("tutorials")))
    for c in categories:
        c.form = CategoryForm(instance=c, prefix=f"c{c.pk}")
    return render(request, "backoffice/tutorials/categories.html", {
        "page_title": "Tutorial categories",
        "page_subtitle": "Group tutorials in the employee training library.",
        "crumbs": [("Tutorials", reverse("backoffice:tutorial_list")), ("Categories", None)],
        "categories": categories,
        "form": form,
        "can_edit": can_edit,
    })


@require_POST
@permission_required_code("content.manage")
def category_edit(request, pk):
    if not can_manage_content_for(request.user, None):
        raise PermissionDenied
    cat = get_object_or_404(TutorialCategory, pk=pk)
    form = CategoryForm(request.POST, instance=cat, prefix=f"c{cat.pk}")
    if form.is_valid():
        form.save()
        audit.log(request, "category.edit", cat)
        messages.success(request, "Category saved.")
    else:
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("backoffice:category_list")


@require_POST
@permission_required_code("content.manage")
def category_delete(request, pk):
    if not can_manage_content_for(request.user, None):
        raise PermissionDenied
    cat = get_object_or_404(TutorialCategory, pk=pk)
    audit.log(request, "category.delete", cat, name=cat.name)
    cat.delete()
    messages.success(request, "Category deleted. Its tutorials are now uncategorised.")
    return redirect("backoffice:category_list")
