from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.choices import ContentStatus
from apps.projects.models import GuidelineAck, Project, ProjectMember
from apps.storage.services import media_url
from apps.training.services import onboarding_for_user

from ..helpers import crumbs, tests_with_state
from ..scope import portal_view
from .dashboard import annotate_progress
from .feedback import annotate_recipients


def _project_or_404(scope, slug):
    member = next((m for m in scope.memberships if m.project.slug == slug), None)
    if member is None:
        raise Http404("প্রজেক্টটি পাওয়া যায়নি")
    return member.project, member


@portal_view
def project_list(request):
    scope = request.portal
    projects = {
        p.pk: p for p in Project.objects.filter(pk__in=scope.project_ids).annotate(
            n_guidelines=Count("guidelines", distinct=True),
            n_tutorials=Count("tutorials", filter=Q(tutorials__status=ContentStatus.PUBLISHED), distinct=True),
            n_members=Count("members", distinct=True),
        )
    }
    onboarding = {s["project"].pk: s for s in onboarding_for_user(request.user) if s["project"]}
    rows = [
        {"member": m, "project": projects.get(m.project_id, m.project), "onboarding": onboarding.get(m.project_id)}
        for m in scope.memberships
    ]
    return render(request, "portal/project_list.html", {
        "rows": rows,
        "page_title": "আমার প্রজেক্ট",
        "page_subtitle": "যেসব প্রজেক্টে আপনি আছেন — সাথে তাদের গাইডলাইন, ট্রেনিং আর অনবোর্ডিং।",
        "crumbs": crumbs(("আমার প্রজেক্ট", None)),
    })


@portal_view
def project_detail(request, slug):
    scope, user = request.portal, request.user
    project, member = _project_or_404(scope, slug)

    if member.team_id:
        teammates = ProjectMember.objects.filter(project=project, team_id=member.team_id).exclude(user=user).count()
    else:
        teammates = ProjectMember.objects.filter(project=project).exclude(user=user).count()
    project_members = ProjectMember.objects.filter(project=project).count()

    guidelines = list(project.guidelines.select_related("document").order_by("order", "title"))
    acks = {a.guideline_id: a for a in GuidelineAck.objects.filter(user=user, guideline__in=guidelines)}
    for g in guidelines:
        g.my_ack = acks.get(g.pk)
        g.ack_current = bool(g.my_ack and g.my_ack.version == g.version)

    tutorials = list(
        annotate_progress(scope.tutorials().filter(project=project), user)
        .select_related("category", "project", "video", "video__thumbnail")
        .order_by("-published_at")[:12]
    )
    feedback = list(
        annotate_recipients(scope.recipients().filter(feedback__project=project), user)
        .select_related("feedback", "feedback__team", "feedback__test")
        .order_by("-feedback__published_at")[:8]
    )
    tests = tests_with_state(scope, scope.tests().filter(project=project))
    onboarding = next((s for s in onboarding_for_user(user) if s["project"] and s["project"].pk == project.pk), None)
    if onboarding:
        onboarding["next"] = next((i for i in onboarding["steps"] if not i["done_at"]), None)

    return render(request, "portal/project_detail.html", {
        "project": project,
        "member": member,
        "teammates": teammates,
        "project_members": project_members,
        "guidelines": guidelines,
        "guidelines_unread": sum(1 for g in guidelines if not g.ack_current),
        "tutorials": tutorials,
        "feedback": feedback,
        "tests": tests,
        "onboarding": onboarding,
        "crumbs": crumbs(("আমার প্রজেক্ট", reverse("portal:projects")), (project.name, None)),
    })


@portal_view
def guideline_detail(request, slug, pk):
    scope = request.portal
    project, member = _project_or_404(scope, slug)
    guideline = get_object_or_404(project.guidelines.select_related("document"), pk=pk)
    ack = GuidelineAck.objects.filter(guideline=guideline, user=request.user).first()
    document = guideline.document
    others = list(project.guidelines.exclude(pk=guideline.pk).order_by("order", "title"))
    return render(request, "portal/guideline_detail.html", {
        "project": project,
        "member": member,
        "guideline": guideline,
        "ack": ack,
        "ack_current": bool(ack and ack.version == guideline.version),
        "document": document,
        "document_url": media_url(document, request.user) if document else "",
        "document_download_url": media_url(document, request.user, download=True) if document else "",
        "others": others,
        "crumbs": crumbs(
            ("আমার প্রজেক্ট", reverse("portal:projects")), (project.name, project.get_absolute_url()), (guideline.title, None)
        ),
    })


@require_POST
@portal_view
def guideline_ack(request, slug, pk):
    project, _ = _project_or_404(request.portal, slug)
    guideline = get_object_or_404(project.guidelines, pk=pk)
    GuidelineAck.objects.update_or_create(guideline=guideline, user=request.user, defaults={"version": guideline.version})
    messages.success(request, f"ধন্যবাদ — “{guideline.title}” v{guideline.version} পড়েছেন বলে নিশ্চিত করেছেন।")
    return redirect("portal:guideline_detail", slug=project.slug, pk=guideline.pk)
