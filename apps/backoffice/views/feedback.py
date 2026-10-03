from django.contrib import messages
from django.db.models import Count, Exists, IntegerField, OuterRef, Q, Subquery
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.permissions import can_manage_content_for, project_scope
from apps.assessments.models import Test, TestAttempt, TestKind
from apps.assessments.services import assign_test
from apps.core import audit
from apps.core.choices import ContentStatus
from apps.feedback.models import Feedback, FeedbackCadence, FeedbackRecipient, Severity
from apps.feedback.services import add_recipients, publish_feedback

from ..forms import AssignPeopleForm, FeedbackForm, TestLinkForm
from ..helpers import (
    assignable_employees,
    csv_response,
    day_end,
    day_start,
    employee_scope,
    get_content,
    paginate,
    parse_date,
    parse_float,
    pct,
    redirect_back,
    staff_projects,
    wants_csv,
)


# ── Tracking query (shared by the feedback detail page and the global tracking page) ──

def tracking_rows(qs):
    """Annotate FeedbackRecipient rows with the employee's result on the linked test."""
    submitted = TestAttempt.objects.filter(test_id=OuterRef("feedback__test_id"), user_id=OuterRef("user_id"), submitted_at__isnull=False)
    return qs.annotate(
        best_score=Subquery(submitted.order_by("-score").values("score")[:1]),
        attempt_count=Subquery(
            submitted.order_by().values("user_id").annotate(c=Count("pk")).values("c")[:1], output_field=IntegerField()
        ),
        last_submitted=Subquery(submitted.order_by("-submitted_at").values("submitted_at")[:1]),
        has_passed=Exists(submitted.filter(passed=True)),
        has_open=Exists(TestAttempt.objects.filter(test_id=OuterRef("feedback__test_id"), user_id=OuterRef("user_id"), submitted_at__isnull=True)),
    )


COMPLETED_Q = Q(watched_at__isnull=False) & (Q(feedback__test__isnull=True) | Q(has_passed=True))


def decorate(row):
    """Compute display values: test column + overall status (Passed / Review / Pending)."""
    fb = row.feedback
    if not fb.test_id:
        row.test_label = "No test"
        row.result = "completed" if row.watched_at else "pending"
    else:
        if row.attempt_count:
            row.test_label = "Completed"
        elif row.has_open:
            row.test_label = "In progress"
        else:
            row.test_label = "Not started"
        row.result = "passed" if row.has_passed else "review" if row.attempt_count else "pending"
    row.result_label = {"passed": "Passed", "review": "Review", "pending": "Pending", "completed": "Completed"}[row.result]
    return row


def _apply_tracking_filters(request, rows, f):
    if f.get("q"):
        q = f["q"]
        rows = rows.filter(Q(user__name__icontains=q) | Q(user__email__icontains=q) | Q(user__employee_id__icontains=q))
    if f.get("employee", "").isdigit():
        rows = rows.filter(user_id=int(f["employee"]))
    state = f.get("state")
    if state == "completed":
        rows = rows.filter(COMPLETED_Q)
    elif state == "pending":
        rows = rows.exclude(COMPLETED_Q)
    elif state == "unseen":
        rows = rows.filter(first_viewed_at__isnull=True)
    elif state == "not_watched":
        rows = rows.filter(watched_at__isnull=True)
    elif state == "watched":
        rows = rows.filter(watched_at__isnull=False)
    elif state == "passed":
        rows = rows.filter(has_passed=True)
    elif state == "review":
        rows = rows.filter(feedback__test__isnull=False, has_passed=False, attempt_count__gt=0)
    smin, smax = parse_float(f.get("score_min")), parse_float(f.get("score_max"))
    if smin is not None:
        rows = rows.filter(best_score__gte=smin)
    if smax is not None:
        rows = rows.filter(best_score__lte=smax)
    return rows


TRACKING_HEADER = ["Employee", "Employee ID", "Email", "Feedback", "Topic", "Project", "Team", "Published", "Opened at",
                   "Watched", "Watched %", "Watched at", "Acknowledged at", "Test", "Best score %", "Attempts", "Status"]


def _tracking_csv(name, rows):
    def gen():
        for r in rows.iterator():
            decorate(r)
            fb = r.feedback
            yield [r.user.name, r.user.employee_id, r.user.email, fb.display_number, fb.topic, fb.project.code,
                   fb.team.name if fb.team_id else "Whole project", fb.published_at, r.first_viewed_at,
                   "Yes" if r.watched_at else "No", round(r.percent), r.watched_at, r.acknowledged_at, r.test_label,
                   round(r.best_score) if r.best_score is not None else "", r.attempt_count or 0, r.result_label]
    return csv_response(name, TRACKING_HEADER, gen())


# ── List / create / edit ────────────────────────────────────────────────────

@permission_required_code("content.manage")
def feedback_list(request):
    user = request.user
    qs = project_scope(Feedback.objects.all(), user).select_related("project", "team", "test", "created_by")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "project", "status", "severity", "cadence")}
    if f["q"]:
        q = f["q"].lstrip("#")
        cond = Q(topic__icontains=f["q"]) | Q(summary__icontains=f["q"])
        if q.isdigit():
            cond |= Q(number=int(q))
        qs = qs.filter(cond)
    if f["project"].isdigit():
        qs = qs.filter(project_id=int(f["project"]))
    if f["status"] in ContentStatus.values:
        qs = qs.filter(status=f["status"])
    if f["severity"] in Severity.values:
        qs = qs.filter(severity=f["severity"])
    if f["cadence"] in FeedbackCadence.values:
        qs = qs.filter(cadence=f["cadence"])
    passers = (TestAttempt.objects.filter(test_id=OuterRef("test_id"), passed=True).order_by()
               .values("test_id").annotate(c=Count("user", distinct=True)).values("c")[:1])
    qs = qs.annotate(
        total=Count("recipients"),
        watched=Count("recipients", filter=Q(recipients__watched_at__isnull=False)),
        seen=Count("recipients", filter=Q(recipients__first_viewed_at__isnull=False)),
        passed=Subquery(passers, output_field=IntegerField()),
    ).order_by("-number")
    page = paginate(request, qs)
    for fb in page:
        fb.watch_pct = pct(fb.watched, fb.total)
        fb.pass_pct = pct(fb.passed or 0, fb.total) if fb.test_id else None
    return render(request, "backoffice/feedback/list.html", {
        "page_title": "Feedback",
        "page_subtitle": "Daily and weekly QA feedback with videos and short tests.",
        "crumbs": [("Feedback", None)],
        "page": page,
        "projects": staff_projects(user).order_by("name"),
        "statuses": ContentStatus.choices,
        "severities": Severity.choices,
        "cadences": FeedbackCadence.choices,
        "filters": f,
    })


def _feedback_form(request, fb=None):
    initial = {}
    if fb is None and request.GET.get("project", "").isdigit():
        initial["project"] = int(request.GET["project"])
    form = FeedbackForm(request.POST or None, instance=fb, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if fb is None:
            obj.created_by = request.user
        obj.save()
        audit.log(request, "feedback.edit" if fb else "feedback.create", obj)
        then = request.POST.get("then")
        if then == "test" and not obj.test_id:
            return _create_test_for(request, obj)
        if then == "publish":
            return _publish(request, obj)
        messages.success(request, f"Feedback {obj.display_number} saved" + (" as a draft." if not obj.is_published else "."))
        return redirect("backoffice:feedback_detail", pk=obj.pk)
    crumbs = [("Feedback", reverse("backoffice:feedback_list"))]
    crumbs += [(fb.display_number, reverse("backoffice:feedback_detail", args=[fb.pk])), ("Edit", None)] if fb else [("New feedback", None)]
    return render(request, "backoffice/feedback/form.html", {
        "page_title": f"Edit feedback {fb.display_number}" if fb else "New feedback",
        "page_subtitle": "Explain the mistake and the correct way, attach a video, and optionally a short test.",
        "crumbs": crumbs,
        "form": form,
        "feedback": fb,
    })


@permission_required_code("content.manage")
def feedback_create(request):
    return _feedback_form(request)


@permission_required_code("content.manage")
def feedback_edit(request, pk):
    return _feedback_form(request, get_content(request, Feedback, pk, manage=True, select=("video__thumbnail", "test")))


# ── Detail (tracking table) ─────────────────────────────────────────────────

@permission_required_code("content.manage")
def feedback_detail(request, pk):
    user = request.user
    fb = get_content(request, Feedback, pk, select=("project", "team", "test", "video__thumbnail", "created_by"))
    can_edit = can_manage_content_for(user, fb.project)
    base = tracking_rows(FeedbackRecipient.objects.filter(feedback=fb, user__in=employee_scope(user))
                         .select_related("user", "feedback__test", "feedback__project", "feedback__team"))
    summary = base.aggregate(
        total=Count("pk"), seen=Count("pk", filter=Q(first_viewed_at__isnull=False)),
        watched=Count("pk", filter=Q(watched_at__isnull=False)), acked=Count("pk", filter=Q(acknowledged_at__isnull=False)),
    )
    summary["passed"] = base.filter(has_passed=True).count() if fb.test_id else None
    summary["completed"] = base.filter(COMPLETED_Q).count()
    f = {k: request.GET.get(k, "").strip() for k in ("q", "state", "score_min", "score_max")}
    rows = _apply_tracking_filters(request, base, f).order_by("watched_at", "user__name")
    if wants_csv(request):
        audit.log(request, "feedback.export", fb)
        return _tracking_csv(f"feedback-{fb.number:03d}-tracking", rows)
    page = paginate(request, rows, 50)
    for r in page:
        decorate(r)
    question_count = fb.test.questions.count() if fb.test_id else 0
    link_form = None
    if can_edit and not fb.test_id:
        link_form = TestLinkForm(tests=_linkable_tests(user, fb))
    add_form = None
    if can_edit and fb.is_published:
        candidates = assignable_employees(user).filter(memberships__project=fb.project).exclude(feedback_received__feedback=fb)
        add_form = AssignPeopleForm(user=user, queryset=candidates)
    return render(request, "backoffice/feedback/detail.html", {
        "page_title": None,
        "crumbs": [("Feedback", reverse("backoffice:feedback_list")), (fb.display_number, None)],
        "fb": fb,
        "can_edit": can_edit,
        "page": page,
        "summary": summary,
        "watch_pct": pct(summary["watched"], summary["total"]),
        "seen_pct": pct(summary["seen"], summary["total"]),
        "pass_pct": pct(summary["passed"], summary["total"]) if fb.test_id else None,
        "filters": f,
        "question_count": question_count,
        "link_form": link_form,
        "add_form": add_form,
    })


def _linkable_tests(user, fb):
    return project_scope(Test.objects.filter(feedback__isnull=True, project=fb.project), user).exclude(
        status=ContentStatus.ARCHIVED).order_by("-created_at")


def _publish(request, fb):
    if fb.test_id and not fb.test.questions.exists():
        messages.error(request, "The linked test has no questions yet — add questions (or unlink the test) before publishing.")
        return redirect("backoffice:feedback_detail", pk=fb.pk)
    n = publish_feedback(fb)
    audit.log(request, "feedback.publish", fb, recipients=n)
    team = f"team {fb.team.name}" if fb.team_id else "the whole project"
    messages.success(request, f"Feedback {fb.display_number} is published to {team}: {n} employee(s) notified by email and in the portal.")
    return redirect("backoffice:feedback_detail", pk=fb.pk)


@require_POST
@permission_required_code("content.manage")
def feedback_publish(request, pk):
    return _publish(request, get_content(request, Feedback, pk, manage=True, select=("test", "team", "project")))


@require_POST
@permission_required_code("content.manage")
def feedback_status(request, pk):
    fb = get_content(request, Feedback, pk, manage=True)
    action = request.POST.get("action")
    if action in ("unpublish", "archive"):
        fb.status = ContentStatus.DRAFT if action == "unpublish" else ContentStatus.ARCHIVED
        fb.save(update_fields=["status", "updated_at"])
        audit.log(request, f"feedback.{action}", fb)
        messages.success(request, "Feedback moved back to draft." if action == "unpublish" else "Feedback archived. Tracking history is kept.")
    elif action == "delete" and fb.status != ContentStatus.PUBLISHED:
        audit.log(request, "feedback.delete", fb, number=fb.number)
        fb.delete()
        messages.success(request, "Feedback deleted.")
        return redirect("backoffice:feedback_list")
    return redirect_back(request, reverse("backoffice:feedback_detail", args=[fb.pk]))


@require_POST
@permission_required_code("content.manage")
def feedback_recipients(request, pk):
    fb = get_content(request, Feedback, pk, manage=True)
    if not fb.is_published:
        messages.error(request, "Publish the feedback first.")
        return redirect("backoffice:feedback_detail", pk=fb.pk)
    form = AssignPeopleForm(request.POST, user=request.user, queryset=assignable_employees(request.user).filter(memberships__project=fb.project))
    if form.is_valid():
        n = add_recipients(fb, form.cleaned_data["users"])
        audit.log(request, "feedback.assign", fb, users=[u.pk for u in form.cleaned_data["users"]])
        messages.success(request, f"Sent to {n} more employee(s).")
    else:
        messages.error(request, "Select at least one employee.")
    return redirect("backoffice:feedback_detail", pk=fb.pk)


# ── Linked test ─────────────────────────────────────────────────────────────

def _create_test_for(request, fb):
    test = Test.objects.create(
        title=f"Feedback {fb.display_number} check — {fb.topic}"[:200], kind=TestKind.FEEDBACK, project=fb.project,
        description=f"A short check after feedback {fb.display_number}: {fb.topic}.", passing_score=80, attempt_limit=2,
        created_by=request.user,
    )
    fb.test = test
    fb.save(update_fields=["test", "updated_at"])
    audit.log(request, "feedback.test_create", fb, test=test.pk)
    messages.success(request, f"Test created and linked to {fb.display_number}. Add the questions below.")
    return redirect(reverse("backoffice:test_builder", args=[test.pk]) + "#add-question")


@require_POST
@permission_required_code("content.manage")
def feedback_test_create(request, pk):
    fb = get_content(request, Feedback, pk, manage=True)
    if fb.test_id:
        return redirect("backoffice:test_builder", pk=fb.test_id)
    return _create_test_for(request, fb)


@require_POST
@permission_required_code("content.manage")
def feedback_test_link(request, pk):
    fb = get_content(request, Feedback, pk, manage=True, select=("test",))
    action = request.POST.get("action", "link")
    if action == "unlink" and fb.test_id:
        old = fb.test_id
        fb.test = None
        fb.save(update_fields=["test", "updated_at"])
        audit.log(request, "feedback.test_unlink", fb, test=old)
        messages.success(request, "Test unlinked. Existing test assignments are kept.")
        return redirect("backoffice:feedback_detail", pk=fb.pk)
    form = TestLinkForm(request.POST, tests=_linkable_tests(request.user, fb))
    if not fb.test_id and form.is_valid():
        test = form.cleaned_data["test"]
        fb.test = test
        fb.save(update_fields=["test", "updated_at"])
        if fb.is_published and test.is_published:
            assign_test(test, [r.user for r in fb.recipients.select_related("user")], assigned_by=request.user)
        audit.log(request, "feedback.test_link", fb, test=test.pk)
        messages.success(request, f"“{test.title}” is now linked to {fb.display_number}.")
    else:
        messages.error(request, "Choose a test from the same project that isn't linked to other feedback.")
    return redirect("backoffice:feedback_detail", pk=fb.pk)


# ── Global tracking ─────────────────────────────────────────────────────────

@permission_required_code("content.manage")
def feedback_tracking(request):
    user = request.user
    base = project_scope(
        FeedbackRecipient.objects.filter(feedback__status__in=[ContentStatus.PUBLISHED, ContentStatus.ARCHIVED],
                                         user__in=employee_scope(user)),
        user, field="feedback__project",
    ).select_related("user", "feedback__project", "feedback__team", "feedback__test")
    rows = tracking_rows(base)
    f = {k: request.GET.get(k, "").strip() for k in ("q", "employee", "project", "feedback", "date_from", "date_to", "state", "score_min", "score_max")}
    if f["project"].isdigit():
        rows = rows.filter(feedback__project_id=int(f["project"]))
    if f["feedback"].isdigit():
        rows = rows.filter(feedback_id=int(f["feedback"]))
    d_from, d_to = parse_date(f["date_from"]), parse_date(f["date_to"])
    if d_from:
        rows = rows.filter(feedback__published_at__gte=day_start(d_from))
    if d_to:
        rows = rows.filter(feedback__published_at__lte=day_end(d_to))
    rows = _apply_tracking_filters(request, rows, f).order_by("-feedback__number", "user__name")
    if wants_csv(request):
        audit.log(request, "feedback.tracking_export", None)
        return _tracking_csv("feedback-tracking", rows)
    summary = rows.aggregate(total=Count("pk"), seen=Count("pk", filter=Q(first_viewed_at__isnull=False)),
                             watched=Count("pk", filter=Q(watched_at__isnull=False)))
    summary["completed"] = rows.filter(COMPLETED_Q).count()
    page = paginate(request, rows, 50)
    for r in page:
        decorate(r)
    feedback_choices = project_scope(Feedback.objects.exclude(status=ContentStatus.DRAFT), user).select_related("project").order_by("-number")
    return render(request, "backoffice/feedback/tracking.html", {
        "page_title": "Feedback tracking",
        "page_subtitle": "Exactly who has seen each feedback item, watched the video and passed the test — and who has not.",
        "crumbs": [("Feedback", reverse("backoffice:feedback_list")), ("Tracking", None)],
        "page": page,
        "summary": summary,
        "filters": f,
        "projects": staff_projects(user).order_by("name"),
        "feedback_choices": feedback_choices,
        "employees": employee_scope(user).filter(feedback_received__isnull=False).distinct().order_by("name"),
        "states": [("completed", "Completed"), ("pending", "Pending"), ("unseen", "Not opened"), ("not_watched", "Not watched"),
                   ("watched", "Watched"), ("review", "Test failed / review"), ("passed", "Test passed")],
    })
