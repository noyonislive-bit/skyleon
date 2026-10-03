from datetime import timedelta

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from apps.core.choices import ProgressStatus
from apps.training.models import (
    Cadence,
    OnboardingStep,
    TutorialCategory,
    TutorialProgress,
)
from apps.training.services import get_or_create_progress, record_tutorial_heartbeat

from ..helpers import (
    crumbs,
    heartbeat_allowed,
    paginate,
    player_config,
    read_json,
    trusted_duration,
)
from ..scope import portal_api, portal_view
from ..templatetags.portal_tags import choice_bn
from .dashboard import NEW_DAYS, annotate_progress

STATUS_FILTERS = [
    ("required", "বাধ্যতামূলক"),
    ("not_started", "শুরু হয়নি"),
    ("in_progress", "চলছে"),
    ("completed", "সম্পন্ন"),
]


@portal_view
def training(request):
    scope, user = request.portal, request.user
    now = timezone.now()
    qs = annotate_progress(scope.tutorials(), user).select_related("category", "project", "video", "video__thumbnail")

    f = {k: (request.GET.get(k) or "").strip() for k in ("q", "category", "project", "cadence", "status")}
    if f["q"]:
        qs = qs.filter(Q(title__icontains=f["q"]) | Q(description__icontains=f["q"]))
    if f["category"]:
        qs = qs.filter(category__slug=f["category"])
    if f["project"] == "company":
        qs = qs.filter(project__isnull=True)
    elif f["project"]:
        qs = qs.filter(project__slug=f["project"])
    if f["cadence"] in Cadence.values:
        qs = qs.filter(cadence=f["cadence"])
    if f["status"] == "required":
        qs = qs.filter(is_required=True)
    elif f["status"] in ProgressStatus.values:
        qs = qs.filter(my_status=f["status"])

    qs = qs.annotate(
        sort_key=Case(
            When(Q(is_required=True) & ~Q(my_status=ProgressStatus.COMPLETED), then=Value(0)),
            When(~Q(my_status=ProgressStatus.COMPLETED), then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    ).order_by("sort_key", "-published_at", "-pk")
    page = paginate(request, qs, 18)

    categories = TutorialCategory.objects.filter(tutorials__in=scope.tutorials()).distinct().order_by("order", "name")
    return render(request, "portal/training.html", {
        "page": page,
        "f": f,
        "filtered": any(f.values()),
        "categories": categories,
        "projects": [m.project for m in scope.memberships],
        "cadences": [(value, choice_bn("cadence", value)) for value in Cadence.values],
        "status_filters": STATUS_FILTERS,
        "new_since": now - timedelta(days=NEW_DAYS),
        "page_title": "ট্রেনিং লাইব্রেরি",
        "page_subtitle": "প্রজেক্টের টিউটোরিয়াল, দৈনিক ও সাপ্তাহিক ট্রেনিং ভিডিও আর রেফারেন্স ম্যাটেরিয়াল।",
        "crumbs": crumbs(("ট্রেনিং", None)),
    })


@portal_view
def tutorial_detail(request, pk):
    scope, user = request.portal, request.user
    tutorial = get_object_or_404(
        scope.tutorials().select_related("category", "project", "video", "video__thumbnail", "created_by"), pk=pk
    )
    progress = get_or_create_progress(tutorial, user)
    if progress.first_viewed_at is None or progress.last_viewed_at is None:
        now = timezone.now()
        progress.first_viewed_at = progress.first_viewed_at or now
        progress.last_viewed_at = now
        progress.save(update_fields=["first_viewed_at", "last_viewed_at"])
    player = player_config(
        tutorial.video, user,
        heartbeat_url=reverse("portal:tutorial_heartbeat", args=[tutorial.pk]),
        row=progress,
        enforce=tutorial.is_required and not progress.is_completed,
        completed=progress.is_completed,
    )

    related_q = Q(project=tutorial.project) if tutorial.project_id else Q(project__isnull=True)
    if tutorial.category_id:
        related_q |= Q(category=tutorial.category)
    related = list(
        annotate_progress(scope.tutorials().filter(related_q).exclude(pk=tutorial.pk), user)
        .select_related("category", "project", "video", "video__thumbnail")
        .order_by("-published_at")[:4]
    )
    steps = list(
        OnboardingStep.objects.filter(tutorial=tutorial).filter(scope.in_scope()).select_related("project")[:3]
    )
    is_new = bool(tutorial.published_at and tutorial.published_at >= timezone.now() - timedelta(days=NEW_DAYS))
    return render(request, "portal/tutorial_detail.html", {
        "tutorial": tutorial,
        "progress": progress,
        "player": player,
        "related": related,
        "onboarding_steps": steps,
        "is_new": is_new,
        "new_since": timezone.now() - timedelta(days=NEW_DAYS),
        "crumbs": crumbs(("ট্রেনিং", reverse("portal:training")), (tutorial.title, None)),
    })


@portal_api
def tutorial_heartbeat(request, pk):
    scope = request.portal
    tutorial = scope.tutorials().select_related("video").filter(pk=pk).first()
    if tutorial is None:
        return JsonResponse({"error": "টিউটোরিয়ালটি পাওয়া যায়নি।"}, status=404)
    if tutorial.video is None:
        return JsonResponse({"error": "এই টিউটোরিয়ালে কোনো ভিডিও নেই।"}, status=400)
    data = read_json(request)
    duration = trusted_duration(tutorial.video, data.get("duration"))
    if duration is None:
        return JsonResponse({"error": "ভিডিওর দৈর্ঘ্য জানা যায়নি।"}, status=400)
    progress = get_or_create_progress(tutorial, request.user)
    throttled = False
    with transaction.atomic():
        progress = TutorialProgress.objects.select_for_update().get(pk=progress.pk)
        if heartbeat_allowed(progress, timezone.now()):
            progress = record_tutorial_heartbeat(
                progress, duration=duration, ranges=data.get("ranges"), position=data.get("position")
            )
        else:
            throttled = True
    completed_at = timezone.localtime(progress.completed_at) if progress.completed_at else None
    return JsonResponse({
        "percent": round(progress.percent, 1),
        "status": progress.status,
        "completed": progress.is_completed,
        "watched_seconds": round(progress.watched_seconds, 1),
        "position": progress.last_position_sec,
        "throttled": throttled,
        "completed_at": date_format(completed_at, "j M Y · H:i") if completed_at else None,
    })
