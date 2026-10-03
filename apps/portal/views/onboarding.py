from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.assessments.services import test_state
from apps.core.choices import ContentStatus
from apps.projects.models import GuidelineAck
from apps.training.models import OnboardingStep, TutorialProgress
from apps.training.services import complete_manual_step, onboarding_for_user

from ..helpers import crumbs, state_badge
from ..scope import attempts_by_test, portal_view


def enrich_sections(scope, sections):
    """Attach the user's state for each step's tutorial / guideline / test / qualification (4 queries)."""
    user = scope.user
    items = [i for sec in sections for i in sec["steps"]]
    tutorial_ids = {i["step"].tutorial_id for i in items if i["step"].tutorial_id}
    guideline_ids = {i["step"].guideline_id for i in items if i["step"].guideline_id}
    tests = {i["step"].test_id: i["step"].test for i in items if i["step"].test_id}
    progress = {
        p.tutorial_id: p for p in TutorialProgress.objects.filter(user=user, tutorial_id__in=tutorial_ids)
    } if tutorial_ids else {}
    acks = {
        a.guideline_id: a for a in GuidelineAck.objects.filter(user=user, guideline_id__in=guideline_ids)
    } if guideline_ids else {}
    attempts = attempts_by_test(user, tests.keys()) if tests else {}

    for sec in sections:
        sec["member"] = scope.membership(sec["project"].pk) if sec["project"] else None
        current_set = False
        for item in sec["steps"]:
            step = item["step"]
            item["done"] = item["done_at"] is not None
            item["blocked"] = item["locked"] and not item["done"]  # done steps stay visible even after a gap
            item["current"] = not item["done"] and not item["locked"] and not current_set
            if item["current"]:
                current_set = True
            if step.tutorial_id:
                item["tutorial_progress"] = progress.get(step.tutorial_id)
                item["tutorial_available"] = step.tutorial.status == ContentStatus.PUBLISHED
            if step.guideline_id:
                ack = acks.get(step.guideline_id)
                item["guideline_ack"] = ack
                item["guideline_current"] = bool(ack and ack.version == step.guideline.version)
            if step.test_id:
                state = test_state(user, step.test, attempts=attempts.get(step.test_id, []))
                item["test_state"] = state
                item["test_badge"] = state_badge(state)
                item["test_available"] = step.test.status == ContentStatus.PUBLISHED
        sec["next"] = next((i for i in sec["steps"] if not i["done"]), None)
    return sections


@portal_view
def onboarding(request):
    sections = enrich_sections(request.portal, onboarding_for_user(request.user))
    total = sum(s["total"] for s in sections)
    done = sum(s["done"] for s in sections)
    return render(request, "portal/onboarding.html", {
        "sections": sections,
        "overall_percent": round(done / total * 100) if total else 0,
        "overall_done": done,
        "overall_total": total,
        "page_title": "অনবোর্ডিং",
        "page_subtitle": "প্রোডাকশনের কাজের জন্য কোয়ালিফাইড হতে ধাপগুলো একটার পর একটা শেষ করুন।",
        "crumbs": crumbs(("অনবোর্ডিং", None)),
    })


@require_POST
@portal_view
def complete_step(request, pk):
    step = get_object_or_404(OnboardingStep, pk=pk)
    item = None
    for sec in onboarding_for_user(request.user):
        item = next((i for i in sec["steps"] if i["step"].pk == step.pk), None)
        if item:
            break
    fallback = reverse("portal:onboarding")
    if item is None:
        messages.error(request, "এই ধাপটি আপনার অনবোর্ডিংয়ের অংশ নয়।")
    elif item["locked"]:
        messages.error(request, "আগে আগের ধাপগুলো শেষ করুন।")
    elif item["rule"] != "manual":
        messages.error(request, "এই ধাপের ভিডিও, টেস্ট বা কোয়ালিফিকেশন শেষ হলে এটি নিজে থেকেই সম্পন্ন হবে।")
    elif item["done_at"]:
        messages.info(request, f"“{step.title}” আগেই সম্পন্ন হয়েছে।")
    else:
        complete_manual_step(step, request.user)
        messages.success(request, f"“{step.title}” ধাপটি সম্পন্ন হিসেবে চিহ্নিত হয়েছে।")
    nxt = request.POST.get("next") or ""
    target = nxt if nxt.startswith("/portal/") and not nxt.startswith("//") else fallback
    return redirect(f"{target}#step-{step.pk}")
