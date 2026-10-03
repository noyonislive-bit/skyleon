from django.contrib import messages
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.assessments.models import QuestionType, TestAttempt
from apps.assessments.services import (
    AttemptError,
    attempt_deadline,
    attempt_questions,
    is_past_deadline,
    start_attempt,
    submit_attempt,
    test_state,
)
from apps.storage.models import MediaAsset, MediaKind
from apps.storage.services import media_url

from ..helpers import crumbs, feedback_gate, paginate, state_badge, tests_with_state
from ..scope import attempts_by_test, portal_view
from ..templatetags.portal_tags import choice_bn

TABS = [("pending", "বাকি"), ("completed", "সম্পন্ন"), ("all", "সব")]

# assessments.services.start_attempt raises AttemptError with English texts (shared with the admin panel);
# employees see these Bangla versions.
ATTEMPT_ERRORS_BN = {
    "This test is not available.": "এই টেস্টটি এখন দেওয়া যাবে না।",
    "You have already passed this test.": "আপনি এই টেস্টে আগেই পাস করেছেন।",
    "You have used all attempts for this test.": "এই টেস্টের সব চেষ্টা শেষ।",
    "This test has no questions yet.": "এই টেস্টে এখনো কোনো প্রশ্ন যোগ করা হয়নি।",
}


def attempt_error_bn(exc) -> str:
    message = str(exc)
    if message in ATTEMPT_ERRORS_BN:
        return ATTEMPT_ERRORS_BN[message]
    if any("\u0980" <= ch <= "\u09ff" for ch in message):  # already Bangla
        return message
    return "টেস্টটি এখন শুরু করা যাচ্ছে না।"


@portal_view
def test_list(request):
    scope = request.portal
    rows = tests_with_state(scope)
    now = timezone.now()
    groups = {
        "pending": [r for r in rows if r["is_open"]],
        "completed": [r for r in rows if not r["is_open"]],
        "all": rows,
    }
    tab = request.GET.get("tab")
    if tab not in groups:
        tab = "pending" if groups["pending"] else "all"
    items = sorted(
        groups[tab],
        key=lambda r: (not r["is_open"], r["due_at"] is None, r["due_at"] or now, r["test"].title.lower()),
    )
    return render(request, "portal/test_list.html", {
        "tab": tab,
        "tabs": [{"key": k, "label": label, "count": len(groups[k])} for k, label in TABS],
        "items": items,
        "now": now,
        "page_title": "টেস্ট ও কুইজ",
        "page_subtitle": "আপনাকে দেওয়া ট্রেনিং, অনবোর্ডিং আর ফিডব্যাক টেস্ট।",
        "crumbs": crumbs(("টেস্ট", None)),
    })


def _visible_test_or_404(scope, pk):
    return get_object_or_404(
        scope.tests().select_related("project", "feedback").annotate(
            question_count=Count("questions", distinct=True), total_points=Sum("questions__points")
        ),
        pk=pk,
    )


@portal_view
def test_detail(request, pk):
    scope, user = request.portal, request.user
    test = _visible_test_or_404(scope, pk)
    attempts = attempts_by_test(user, [test.pk]).get(test.pk, [])
    state = test_state(user, test, attempts=attempts)
    recipient, gate = feedback_gate(scope, test)
    return render(request, "portal/test_detail.html", {
        "test": test,
        "state": state,
        "badge": state_badge(state),
        "attempts": [a for a in attempts if a.submitted_at],
        "gate": gate,
        "recipient": recipient,
        "feedback": getattr(test, "feedback", None),
        "crumbs": crumbs(("টেস্ট", reverse("portal:tests")), (test.title, None)),
    })


@require_POST
@portal_view
def test_start(request, pk):
    scope = request.portal
    test = get_object_or_404(scope.tests().select_related("feedback"), pk=pk)
    _, gate = feedback_gate(scope, test)
    if gate:
        messages.warning(request, gate)
        return redirect("portal:test_detail", pk=test.pk)
    try:
        attempt = start_attempt(request.user, test)
    except AttemptError as exc:
        messages.error(request, attempt_error_bn(exc))
        return redirect("portal:test_detail", pk=test.pk)
    return redirect("portal:test_take", attempt_id=attempt.pk)


def _asset_map(ids):
    ids = [i for i in ids if i]
    return {a.pk: a for a in MediaAsset.objects.filter(pk__in=ids)} if ids else {}


def _media(asset, user):
    if asset is None:
        return None
    url = media_url(asset, user)
    if not url:
        return None
    return {"url": url, "kind": asset.kind, "is_video": asset.kind == MediaKind.VIDEO, "name": asset.original_name}


def build_questions(attempt, user, *, reveal=False):
    """
    View-model for the test-taker / result review. Correct answers are only included when
    `reveal` is True (result page) — never while the attempt is open.
    """
    questions = attempt_questions(attempt)
    option_media = _asset_map([o.media_id for q in questions for o in q.options.all()])
    answers = {a["question"]: a for a in (attempt.data or {}).get("answers", [])}
    out = []
    for index, q in enumerate(questions, start=1):
        answer = answers.get(q.pk, {})
        selected = set(answer.get("selected", []))
        options = []
        for o in q.options.all():
            opt = {
                "id": o.pk,
                "text": o.text,
                "media": _media(option_media.get(o.media_id), user) if o.media_id else None,
                "selected": o.pk in selected,
            }
            if reveal:
                opt["is_correct"] = o.is_correct
            options.append(opt)
        out.append({
            "id": q.pk,
            "index": index,
            "prompt": q.prompt,
            "qtype": q.qtype,
            "qtype_label": choice_bn("question_type", q.qtype),
            "multi": q.qtype == QuestionType.MULTI_SELECT,
            "points": q.points,
            "media": _media(q.media, user) if q.media_id else None,
            "image_options": any(opt["media"] for opt in options),
            "options": options,
            "answered": bool(selected),
            "correct": answer.get("correct"),
            "earned": answer.get("points", 0),
            "explanation": q.explanation if reveal else "",
        })
    return out


def _owned_attempt(request, attempt_id):
    return get_object_or_404(TestAttempt.objects.select_related("test", "test__project"), pk=attempt_id, user=request.user)


@portal_view
def test_take(request, attempt_id):
    attempt = _owned_attempt(request, attempt_id)
    if attempt.is_submitted:
        return redirect("portal:result_detail", attempt_id=attempt.pk)
    test = attempt.test
    if not test.is_published or not request.portal.tests().filter(pk=test.pk).exists():
        messages.error(request, "এই টেস্টটি এখন আর আপনার জন্য খোলা নেই।")
        return redirect("portal:tests")
    deadline = attempt_deadline(attempt)
    now = timezone.now()

    if request.method == "POST":
        selections = {}
        for q in attempt_questions(attempt):
            values = request.POST.getlist(f"q_{q.pk}")
            if values:
                selections[str(q.pk)] = values
        attempt = submit_attempt(attempt, selections)
        if attempt.data.get("late"):
            messages.warning(request, "সময়সীমা পার হওয়ার পর উত্তর জমা হয়েছে, তাই উত্তরগুলো গণনা করা হয়নি।")
        elif request.POST.get("auto") == "1":
            messages.info(request, "সময় শেষ — আপনার উত্তরগুলো নিজে থেকেই জমা হয়ে গেছে।")
        return redirect("portal:result_detail", attempt_id=attempt.pk)

    if is_past_deadline(attempt, now):
        submit_attempt(attempt, {})
        messages.warning(request, "এই চেষ্টার সময় আগেই শেষ হয়ে গিয়েছিল, তাই উত্তর ছাড়াই জমা হয়ে গেছে।")
        return redirect("portal:result_detail", attempt_id=attempt.pk)

    questions = build_questions(attempt, request.user, reveal=False)
    remaining = max(0, int((deadline - now).total_seconds())) if deadline else None
    return render(request, "portal/test_take.html", {
        "attempt": attempt,
        "test": test,
        "questions": questions,
        "deadline": deadline,
        "remaining": remaining,
        "crumbs": crumbs(("টেস্ট", reverse("portal:tests")), (test.title, reverse("portal:test_detail", args=[test.pk])),
                         (f"চেষ্টা #{attempt.attempt_number}", None)),
    })


@portal_view
def result_detail(request, attempt_id):
    scope, user = request.portal, request.user
    attempt = _owned_attempt(request, attempt_id)
    if not attempt.is_submitted:
        return redirect("portal:test_take", attempt_id=attempt.pk)
    test = attempt.test
    all_attempts = list(TestAttempt.objects.filter(test=test, user=user).order_by("-attempt_number"))
    state = test_state(user, test, attempts=all_attempts)
    # Correct answers are shown only once they can't be used for a retake: after a pass or the last attempt.
    reveal = test.reveal_answers and state.status in ("passed", "locked")
    reveal_later = test.reveal_answers and not reveal
    questions = build_questions(attempt, user, reveal=reveal)
    visible = scope.tests().filter(pk=test.pk).exists()
    _, gate = feedback_gate(scope, test) if visible else (None, None)
    fb = getattr(test, "feedback", None)
    return render(request, "portal/result_detail.html", {
        "attempt": attempt,
        "test": test,
        "questions": questions,
        "reveal": reveal,
        "reveal_later": reveal_later,
        "state": state,
        "badge": state_badge(state),
        "can_retake": visible and test.is_published and state.can_attempt and not gate,
        "correct_count": sum(1 for q in questions if q["correct"]),
        "feedback": fb,
        "history": [a for a in all_attempts if a.submitted_at],
        "crumbs": crumbs(("ফলাফল", reverse("portal:results")), (f"{test.title} · চেষ্টা #{attempt.attempt_number}", None)),
    })


@portal_view
def results(request):
    qs = (
        TestAttempt.objects.filter(user=request.user, submitted_at__isnull=False)
        .select_related("test", "test__project")
        .order_by("-submitted_at")
    )
    page = paginate(request, qs, 25)
    summary = qs.aggregate(taken=Count("pk"), passed=Count("pk", filter=Q(passed=True)), avg=Avg("score"))
    return render(request, "portal/results.html", {
        "page": page,
        "summary": summary,
        "page_title": "ফলাফলের ইতিহাস",
        "page_subtitle": "আপনার জমা দেওয়া প্রতিটি টেস্ট আর তার স্কোর।",
        "crumbs": crumbs(("ফলাফল", None)),
    })
