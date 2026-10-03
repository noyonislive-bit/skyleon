from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts.forms import ProfileForm
from apps.assessments.models import TestAttempt
from apps.core.choices import ProgressStatus
from apps.training.models import TutorialProgress

from ..forms import PortalPasswordChangeForm
from ..helpers import crumbs
from ..scope import portal_view
from .feedback import annotate_recipients


@portal_view
def profile(request):
    user = request.user
    action = request.POST.get("action") if request.method == "POST" else None
    profile_form = ProfileForm(request.POST if action == "profile" else None, instance=user, prefix="profile")
    password_form = PortalPasswordChangeForm(user, request.POST if action == "password" else None, prefix="pw")

    if action == "profile" and profile_form.is_valid():
        profile_form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("portal:profile")
    if action == "password" and password_form.is_valid():
        password_form.save()
        update_session_auth_hash(request, password_form.user)
        messages.success(request, "Your password has been changed.")
        return redirect(reverse("portal:profile") + "#security")

    stats = TutorialProgress.objects.filter(user=user).aggregate(
        completed=Count("pk", filter=Q(status=ProgressStatus.COMPLETED))
    )
    stats.update(TestAttempt.objects.filter(user=user, submitted_at__isnull=False).aggregate(
        attempts=Count("pk"), passed=Count("pk", filter=Q(passed=True))
    ))
    return render(request, "portal/profile.html", {
        "profile_form": profile_form,
        "password_form": password_form,
        "memberships": request.portal.memberships,
        "stats": stats,
        "active_tab": "profile",
        "page_title": "My profile",
        "page_subtitle": "Your account details, password and personal history.",
        "crumbs": crumbs(("Profile", None)),
    })


@portal_view
def history(request):
    scope, user = request.portal, request.user
    training = list(
        TutorialProgress.objects.filter(user=user, status=ProgressStatus.COMPLETED, tutorial__in=scope.tutorials())
        .select_related("tutorial", "tutorial__project", "tutorial__category")
        .order_by("-completed_at")[:100]
    )
    feedback = list(
        annotate_recipients(scope.recipients(), user)
        .filter(first_viewed_at__isnull=False)
        .select_related("feedback", "feedback__project", "feedback__test")
        .order_by("-first_viewed_at")[:100]
    )
    attempts = list(
        TestAttempt.objects.filter(user=user, submitted_at__isnull=False)
        .select_related("test", "test__project")
        .order_by("-submitted_at")[:100]
    )
    return render(request, "portal/history.html", {
        "training": training,
        "feedback": feedback,
        "attempts": attempts,
        "active_tab": "history",
        "page_title": "My history",
        "page_subtitle": "Your training, feedback and test record.",
        "crumbs": crumbs(("Profile", reverse("portal:profile")), ("History", None)),
    })
