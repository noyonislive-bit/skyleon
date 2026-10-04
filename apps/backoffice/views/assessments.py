from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Exists, Max, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.models import UserStatus
from apps.accounts.permissions import can_manage_content_for, project_scope
from apps.assessments.models import Question, QuestionOption, QuestionType, Test, TestAssignment, TestAttempt, TestKind
from apps.assessments.services import assign_test, publish_test, test_state
from apps.core import audit
from apps.core.choices import ContentStatus

from ..forms import AssignPeopleForm, OptionFormSet, QuestionForm, TestForm, clean_question, tf_key
from ..helpers import (
    assignable_employees,
    csv_response,
    day_end,
    employee_scope,
    get_content,
    paginate,
    pct,
    people_q,
    redirect_back,
    staff_projects,
    wants_csv,
)


def _linked_feedback(test):
    try:
        return test.feedback
    except Exception:  # RelatedObjectDoesNotExist
        return None


def pending_assignments(user):
    """Assignments of published tests to active people in the viewer's scope that have no passed attempt yet
    (the dashboard's "Tests pending" figure and the test list's `?pending=1` filter)."""
    passed = TestAttempt.objects.filter(test=OuterRef("test"), user=OuterRef("user"), passed=True)
    return project_scope(
        TestAssignment.objects.filter(test__status=ContentStatus.PUBLISHED, user__status=UserStatus.ACTIVE)
        .filter(people_q(user)),
        user, field="test__project",
    ).filter(~Exists(passed))


@permission_required_code("content.manage")
def test_list(request):
    user = request.user
    qs = project_scope(Test.objects.all(), user).select_related("project", "feedback")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "project", "kind", "status", "pending")}
    if f["q"]:
        qs = qs.filter(Q(title__icontains=f["q"]) | Q(description__icontains=f["q"]))
    if f["project"] == "global":
        qs = qs.filter(project__isnull=True)
    elif f["project"].isdigit():
        qs = qs.filter(project_id=int(f["project"]))
    if f["kind"] in TestKind.values:
        qs = qs.filter(kind=f["kind"])
    if f["status"] in ContentStatus.values:
        qs = qs.filter(status=f["status"])
    pending = dict(pending_assignments(user).order_by().values_list("test_id").annotate(n=Count("pk")))
    pending_total = None
    if f["pending"] == "1":
        qs = qs.filter(pk__in=list(pending))
        pending_total = sum(pending.get(pk, 0) for pk in qs.values_list("pk", flat=True))
    # Counts cover the same people as the test's results page.
    submitted = Q(attempts__submitted_at__isnull=False) & people_q(user, "attempts__user")
    qs = qs.annotate(
        question_count=Count("questions", distinct=True),
        assigned=Count("assignments", filter=people_q(user, "assignments__user"), distinct=True),
        attempt_count=Count("attempts", filter=submitted, distinct=True),
        takers=Count("attempts__user", filter=submitted, distinct=True),
        passers=Count("attempts__user", filter=submitted & Q(attempts__passed=True), distinct=True),
    ).order_by("-created_at")
    page = paginate(request, qs)
    for t in page:
        t.pass_rate = pct(t.passers, t.takers)
        t.linked_feedback = _linked_feedback(t)
        t.pending = pending.get(t.pk, 0)
    return render(request, "backoffice/tests/list.html", {
        "page_title": "Tests",
        "page_subtitle": "Training, onboarding, feedback and qualification tests with automatic scoring.",
        "crumbs": [("Tests", None)],
        "page": page,
        "projects": staff_projects(user).order_by("name"),
        "kinds": TestKind.choices,
        "statuses": ContentStatus.choices,
        "filters": f,
        "pending_total": pending_total,
    })


def _test_form(request, test=None):
    initial = {}
    if test is None:
        if request.GET.get("project", "").isdigit():
            initial["project"] = int(request.GET["project"])
        if request.GET.get("kind") in TestKind.values:
            initial["kind"] = request.GET["kind"]
    form = TestForm(request.POST or None, instance=test, user=request.user, initial=initial)
    linked = _linked_feedback(test) if test else None
    if request.method == "POST" and form.is_valid():
        if linked and form.cleaned_data.get("project") != linked.project:
            form.add_error("project", f"This test is linked to feedback {linked.display_number}; keep it on {linked.project.code}.")
        else:
            obj = form.save(commit=False)
            if test is None:
                obj.created_by = request.user
            obj.save()
            audit.log(request, "test.edit" if test else "test.create", obj)
            messages.success(request, "Test settings saved." if test else "Test created — now add the questions.")
            return redirect(reverse("backoffice:test_builder", args=[obj.pk]) + ("" if test else "#add-question"))
    crumbs = [("Tests", reverse("backoffice:test_list"))]
    crumbs += [(test.title, reverse("backoffice:test_builder", args=[test.pk])), ("Settings", None)] if test else [("New test", None)]
    return render(request, "backoffice/tests/form.html", {
        "page_title": "Test settings" if test else "New test",
        "page_subtitle": "Scoring is automatic: each question is all-or-nothing and weighted by its points.",
        "crumbs": crumbs,
        "form": form,
        "test": test,
        "linked": linked,
    })


@permission_required_code("content.manage")
def test_create(request):
    return _test_form(request)


@permission_required_code("content.manage")
def test_edit(request, pk):
    return _test_form(request, get_content(request, Test, pk, manage=True))


def _new_question_forms(user, data=None):
    qform = QuestionForm(data, prefix="q", user=user)
    formset = OptionFormSet(data, prefix="opt", initial=None if data else [{}, {}, {}, {}], form_kwargs={"user": user})
    return qform, formset


def _builder_context(request, test, qform=None, formset=None):
    user = request.user
    questions = list(test.questions.select_related("media__thumbnail").prefetch_related("options__media").order_by("order", "pk"))
    if qform is None:
        qform, formset = _new_question_forms(user)
    linked = _linked_feedback(test)
    stats = TestAttempt.objects.filter(people_q(user), test=test, submitted_at__isnull=False).aggregate(
        n=Count("pk"), takers=Count("user", distinct=True), passers=Count("user", filter=Q(passed=True), distinct=True))
    assign_form = None
    can_edit = can_manage_content_for(user, test.project)
    if can_edit and test.is_published:
        candidates = assignable_employees(user).exclude(pk__in=TestAssignment.objects.filter(test=test).values("user_id"))
        if test.project_id:
            candidates = candidates.filter(memberships__project=test.project)
        assign_form = AssignPeopleForm(user=user, queryset=candidates)
    return {
        "page_title": None,
        "crumbs": [("Tests", reverse("backoffice:test_list")), (test.title, None)],
        "test": test,
        "questions": questions,
        "total_points": sum(q.points for q in questions),
        "qform": qform,
        "formset": formset,
        "linked": linked,
        "can_edit": can_edit,
        "stats": stats,
        "pass_rate": pct(stats["passers"], stats["takers"]),
        "assigned_count": test.assignments.filter(people_q(user)).count(),
        "assign_form": assign_form,
        # Questions added now are appended to attempts that are still open (they count towards the score).
        "open_attempts": test.attempts.filter(submitted_at__isnull=True).count() if test.is_published else 0,
        # test_status(action="delete") refuses while ANY attempt exists (also unsubmitted ones and people outside
        # the viewer's scope), so the Delete button follows the same rule.
        "can_delete": can_edit and not test.attempts.exists(),
        "qtypes": QuestionType.choices,
    }


@permission_required_code("content.manage")
def test_builder(request, pk):
    test = get_content(request, Test, pk, select=("project", "created_by"))
    return render(request, "backoffice/tests/builder.html", _builder_context(request, test))


@transaction.atomic
def _save_question(test, qform, options, question=None):
    q = qform.save(commit=False)
    q.test = test
    if question is None:
        q.order = (test.questions.aggregate(m=Max("order"))["m"] or 0) + 1
    q.save()
    existing = {o.pk: o for o in q.options.all()}
    if q.qtype == QuestionType.TRUE_FALSE:
        # Keep existing True/False options (in either language) and only flip the correct answer —
        # attempts store the chosen option ids.
        by_key = {tf_key(o.text): o for o in existing.values()}
        if set(by_key) == {"true", "false"} and len(existing) == 2:
            for opt in options:
                o = by_key[opt["tf"]]
                if o.is_correct != opt["is_correct"]:
                    o.is_correct = opt["is_correct"]
                    o.save(update_fields=["is_correct"])
            return q
        q.options.all().delete()
        for i, opt in enumerate(options):
            QuestionOption.objects.create(question=q, order=i, text=opt["text"], is_correct=opt["is_correct"])
        return q
    keep = set()
    for i, opt in enumerate(options):
        o = existing.get(opt["id"]) if opt["id"] else None
        if o is None:
            o = QuestionOption(question=q)
        o.order, o.text, o.media, o.is_correct = i, opt["text"], opt["media"], opt["is_correct"]
        o.save()
        keep.add(o.pk)
    q.options.exclude(pk__in=keep).delete()
    return q


@permission_required_code("content.manage")
def question_create(request, pk):
    test = get_content(request, Test, pk, manage=True, select=("project",))
    if request.method != "POST":
        return redirect(reverse("backoffice:test_builder", args=[test.pk]) + "#add-question")
    qform, formset = _new_question_forms(request.user, request.POST)
    options = clean_question(qform, formset)
    if options is not None:
        q = _save_question(test, qform, options)
        audit.log(request, "question.create", q, test=test.pk)
        messages.success(request, "Question added.")
        if request.POST.get("then") == "another":
            return redirect(reverse("backoffice:test_builder", args=[test.pk]) + "#add-question")
        return redirect(reverse("backoffice:test_builder", args=[test.pk]) + f"#q-{q.pk}")
    messages.error(request, "The question was not saved — please fix the highlighted problems.")
    ctx = _builder_context(request, test, qform, formset)
    ctx["open_add"] = True
    return render(request, "backoffice/tests/builder.html", ctx)


@permission_required_code("content.manage")
def question_edit(request, pk):
    question = get_object_or_404(Question.objects.select_related("test__project", "media__thumbnail"), pk=pk)
    test = get_content(request, Test, question.test_id, manage=True, select=("project",))
    options = list(question.options.select_related("media").order_by("order", "pk"))
    initial = [{"id": o.pk, "text": o.text, "media": o.media_id, "is_correct": o.is_correct} for o in options]
    if request.method == "POST":
        qform = QuestionForm(request.POST, instance=question, prefix="q", user=request.user)
        formset = OptionFormSet(request.POST, prefix="opt", initial=initial, form_kwargs={"user": request.user})
        cleaned = clean_question(qform, formset)
        if cleaned is not None:
            _save_question(test, qform, cleaned, question)
            audit.log(request, "question.edit", question, test=test.pk)
            messages.success(request, "Question saved.")
            return redirect(reverse("backoffice:test_builder", args=[test.pk]) + f"#q-{question.pk}")
        messages.error(request, "The question was not saved — please fix the highlighted problems.")
    else:
        qform = QuestionForm(instance=question, prefix="q", user=request.user)
        if question.qtype == QuestionType.TRUE_FALSE:
            initial = [{}, {}]
        formset = OptionFormSet(prefix="opt", initial=initial, form_kwargs={"user": request.user})
    position = list(test.questions.order_by("order", "pk").values_list("pk", flat=True)).index(question.pk) + 1
    return render(request, "backoffice/tests/question_form.html", {
        "page_title": f"Edit question {position}",
        "crumbs": [("Tests", reverse("backoffice:test_list")), (test.title, reverse("backoffice:test_builder", args=[test.pk])), (f"Question {position}", None)],
        "test": test,
        "question": question,
        "qform": qform,
        "formset": formset,
        "attempt_count": test.attempts.filter(submitted_at__isnull=False).count(),
    })


@require_POST
@permission_required_code("content.manage")
def question_delete(request, pk):
    question = get_object_or_404(Question, pk=pk)
    test = get_content(request, Test, question.test_id, manage=True)
    audit.log(request, "question.delete", question, test=test.pk)
    question.delete()
    messages.success(request, "Question deleted.")
    return redirect(reverse("backoffice:test_builder", args=[test.pk]) + "#questions")


@require_POST
@permission_required_code("content.manage")
def question_move(request, pk):
    question = get_object_or_404(Question, pk=pk)
    test = get_content(request, Test, question.test_id, manage=True)
    with transaction.atomic():
        qs = list(Question.objects.select_for_update().filter(test=test).order_by("order", "pk"))
        idx = next(i for i, q in enumerate(qs) if q.pk == question.pk)
        target = idx - 1 if request.POST.get("direction") == "up" else idx + 1
        if 0 <= target < len(qs):
            qs[idx], qs[target] = qs[target], qs[idx]
        for i, q in enumerate(qs, start=1):
            if q.order != i:
                Question.objects.filter(pk=q.pk).update(order=i)
    return redirect(reverse("backoffice:test_builder", args=[test.pk]) + f"#q-{question.pk}")


@require_POST
@permission_required_code("content.manage")
def test_publish(request, pk):
    test = get_content(request, Test, pk, manage=True, select=("project",))
    if not test.questions.exists():
        messages.error(request, "Add at least one question before publishing.")
        return redirect("backoffice:test_builder", pk=test.pk)
    bad = [q for q in test.questions.prefetch_related("options") if not any(o.is_correct for o in q.options.all()) or q.options.count() < 2]
    if bad:
        messages.error(request, f"{len(bad)} question(s) need at least two options and a correct answer.")
        return redirect("backoffice:test_builder", pk=test.pk)
    linked = _linked_feedback(test)
    assign = request.POST.get("assign") == "1"
    n = publish_test(test, assign=assign and linked is None, assigned_by=request.user)
    if linked is not None and linked.is_published:
        n = assign_test(test, [r.user for r in linked.recipients.select_related("user")], assigned_by=request.user)
        messages.success(request, f"Test published and assigned to the {n} new recipient(s) of feedback {linked.display_number}.")
    elif assign and test.project_id:
        messages.success(request, f"Test published and assigned to {n} project member(s) — they have been notified.")
    else:
        messages.success(request, "Test published.")
    audit.log(request, "test.publish", test, assigned=n)
    return redirect("backoffice:test_builder", pk=test.pk)


@require_POST
@permission_required_code("content.manage")
def test_status(request, pk):
    test = get_content(request, Test, pk, manage=True)
    action = request.POST.get("action")
    if action in ("unpublish", "archive"):
        test.status = ContentStatus.DRAFT if action == "unpublish" else ContentStatus.ARCHIVED
        test.save(update_fields=["status", "updated_at"])
        audit.log(request, f"test.{action}", test)
        messages.success(request, "Test moved back to draft." if action == "unpublish" else "Test archived. Results are kept.")
    elif action == "delete":
        if test.attempts.exists():
            messages.error(request, "This test has attempts — archive it instead of deleting.")
        else:
            audit.log(request, "test.delete", test, title=test.title)
            test.delete()
            messages.success(request, "Test deleted.")
            return redirect("backoffice:test_list")
    return redirect_back(request, reverse("backoffice:test_builder", args=[test.pk]))


@require_POST
@permission_required_code("content.manage")
def test_assign(request, pk):
    test = get_content(request, Test, pk, manage=True)
    if not test.is_published:
        messages.error(request, "Publish the test before assigning it.")
        return redirect("backoffice:test_builder", pk=test.pk)
    qs = assignable_employees(request.user)
    if test.project_id:
        qs = qs.filter(memberships__project=test.project)
    form = AssignPeopleForm(request.POST, user=request.user, queryset=qs)
    if form.is_valid():
        users = list(form.cleaned_data["users"])
        n = assign_test(test, users, assigned_by=request.user, due_at=day_end(form.cleaned_data["due_date"]))
        audit.log(request, "test.assign", test, users=[u.pk for u in users])
        messages.success(request, f"Assigned to {n} employee(s)." if n else "Those employees already had this test.")
    else:
        messages.error(request, "Select at least one employee.")
    return redirect_back(request, reverse("backoffice:test_builder", args=[test.pk]))


# ── Results ─────────────────────────────────────────────────────────────────

@permission_required_code("content.manage")
def test_results(request, pk):
    user = request.user
    test = get_content(request, Test, pk, select=("project",))
    people_scope = employee_scope(user)
    attempts = list(TestAttempt.objects.filter(test=test, user__in=people_scope).select_related("user").order_by("-attempt_number"))
    by_user = {}
    for a in attempts:
        by_user.setdefault(a.user_id, []).append(a)
    assignments = {a.user_id: a for a in TestAssignment.objects.filter(test=test, user__in=people_scope).select_related("user")}
    people = {a.user_id: a.user for a in assignments.values()}
    people.update({a.user_id: a.user for a in attempts})
    rows = []
    for uid, person in people.items():
        assignment = assignments.get(uid)
        state = test_state(person, test, by_user.get(uid, []), assignment.extra_attempts if assignment else 0)
        submitted = [a for a in by_user.get(uid, []) if a.submitted_at]
        rows.append({
            "user": person, "state": state, "assignment": assignments.get(uid),
            "attempts": len(submitted), "best": state.best_score,
            "last": state.last_attempt, "last_submitted": submitted[0].submitted_at if submitted else None,
        })
    f = {k: request.GET.get(k, "").strip() for k in ("q", "result")}
    if f["q"]:
        q = f["q"].lower()
        rows = [r for r in rows if q in r["user"].name.lower() or q in r["user"].email.lower() or q in (r["user"].employee_id or "").lower()]
    if f["result"] == "passed":
        rows = [r for r in rows if r["state"].status == "passed"]
    elif f["result"] == "failed":
        rows = [r for r in rows if r["state"].status in ("review", "locked")]
    elif f["result"] == "pending":
        rows = [r for r in rows if r["state"].status in ("pending", "in_progress")]
    rows.sort(key=lambda r: ({"passed": 2, "review": 1, "locked": 1, "in_progress": 0, "pending": 0}[r["state"].status], r["user"].name))
    submitted = [a for a in attempts if a.submitted_at]
    if f["q"]:
        allowed = {r["user"].pk for r in rows}
        submitted = [a for a in submitted if a.user_id in allowed]
    if wants_csv(request):
        audit.log(request, "test.export", test)
        if request.GET.get("rows") == "attempts":
            return csv_response(f"test-{test.pk}-attempts", ["Employee", "Employee ID", "Email", "Attempt", "Started", "Submitted",
                                                              "Score %", "Points", "Result"], (
                [a.user.name, a.user.employee_id, a.user.email, a.attempt_number, a.started_at, a.submitted_at,
                 round(a.score, 1) if a.score is not None else "", f"{a.points_earned}/{a.points_total}",
                 "Passed" if a.passed else "Failed"] for a in submitted
            ))
        return csv_response(f"test-{test.pk}-results", ["Employee", "Employee ID", "Email", "Status", "Best score %", "Attempts used",
                                                         "Attempts left", "Last submitted", "Assigned at"], (
            [r["user"].name, r["user"].employee_id, r["user"].email, r["state"].status.replace("_", " ").title(),
             round(r["best"], 1) if r["best"] is not None else "", r["attempts"],
             "Unlimited" if r["state"].attempts_left is None else r["state"].attempts_left, r["last_submitted"],
             r["assignment"].assigned_at if r["assignment"] else ""] for r in rows
        ))
    summary = {
        "people": len(people), "assigned": len(assignments),
        "passed": sum(1 for r in rows if r["state"].status == "passed"),
        "takers": sum(1 for r in rows if r["attempts"]),
        "avg": (sum(a.score for a in submitted if a.score is not None) / len(submitted)) if submitted else None,
    }
    return render(request, "backoffice/tests/results.html", {
        "page_title": None,
        "crumbs": [("Tests", reverse("backoffice:test_list")), (test.title, reverse("backoffice:test_builder", args=[test.pk])), ("Results", None)],
        "test": test,
        "rows": rows,
        "attempts": submitted[:200],
        "summary": summary,
        "pass_rate": pct(summary["passed"], summary["takers"]),
        "filters": f,
        "linked": _linked_feedback(test),
        "can_edit": can_manage_content_for(user, test.project),
    })


@permission_required_code("content.manage")
def attempt_detail(request, pk):
    attempt = get_object_or_404(TestAttempt.objects.select_related("test__project", "user"), pk=pk)
    test = get_content(request, Test, attempt.test_id, select=("project",))
    if not employee_scope(request.user).filter(pk=attempt.user_id).exists():
        from django.http import Http404

        raise Http404
    questions = {q.pk: q for q in Question.objects.filter(test=test).prefetch_related("options__media").select_related("media__thumbnail")}
    answers = {a.get("question"): a for a in (attempt.data or {}).get("answers", [])}
    order = (attempt.data or {}).get("order") or list(questions)
    items = []
    for i, qid in enumerate(order, start=1):
        q = questions.get(qid)
        if q is None:
            continue
        ans = answers.get(qid, {})
        selected = set(ans.get("selected") or [])
        items.append({
            "n": i, "question": q, "correct": ans.get("correct"), "points": ans.get("points", 0), "answered": bool(ans),
            "options": [{"option": o, "selected": o.pk in selected, "is_correct": o.is_correct} for o in q.options.all()],
        })
    others = TestAttempt.objects.filter(test=test, user=attempt.user).order_by("attempt_number")
    return render(request, "backoffice/tests/attempt.html", {
        "page_title": None,
        "crumbs": [("Tests", reverse("backoffice:test_list")), (test.title, reverse("backoffice:test_builder", args=[test.pk])),
                   ("Results", reverse("backoffice:test_results", args=[test.pk])), (f"{attempt.user.name} · #{attempt.attempt_number}", None)],
        "attempt": attempt,
        "test": test,
        "items": items,
        "others": others,
    })
