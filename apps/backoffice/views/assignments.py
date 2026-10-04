"""
Per-person assignment adjustments (employee page, test results, feedback detail):

  * tutorials: change the due date, unassign
  * tests: change the due date, unassign, reset the attempts, grant one extra attempt
  * feedback: remove a recipient

Staff need content.manage, may edit the content's project (can_manage_content_for) and must see
the person (employee_scope). Every action is audit-logged.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.permissions import can_manage_content_for
from apps.assessments.models import Test, TestAssignment
from apps.assessments.services import grant_extra_attempt, reset_attempts
from apps.comms.models import NotificationType
from apps.comms.services import notify
from apps.core import audit
from apps.feedback.models import FeedbackRecipient
from apps.training.models import TutorialProgress

from ..helpers import day_end, employee_scope, get_content, parse_date, redirect_back


def _check(request, project, user_id):
    if not can_manage_content_for(request.user, project):
        raise PermissionDenied
    if not employee_scope(request.user).filter(pk=user_id).exists():
        raise Http404


def _employee_tab(user_id, tab):
    return reverse("backoffice:employee_detail", args=[user_id]) + f"?tab={tab}"


def _posted_due(request):
    """(ok, date|None) — an empty field clears the due date."""
    raw = (request.POST.get("due_date") or "").strip()
    if not raw:
        return True, None
    value = parse_date(raw)
    return value is not None, value


def _due_label(value):
    return f"{value.day} {value:%b %Y}" if value else "no due date"


# ── Tutorials ───────────────────────────────────────────────────────────────

def _progress(request, pk):
    row = get_object_or_404(TutorialProgress.objects.select_related("tutorial__project", "user"), pk=pk)
    _check(request, row.tutorial.project, row.user_id)
    return row


@require_POST
@permission_required_code("content.manage")
def progress_unassign(request, pk):
    row = _progress(request, pk)
    tutorial, person = row.tutorial, row.user
    if not row.assigned:
        messages.info(request, f"“{tutorial.title}” is not assigned to {person.name}.")
    elif row.first_viewed_at or row.watched_seconds:
        # Keep what they have already watched — the row becomes a self-started (optional) one.
        row.assigned, row.due_at = False, None
        row.save(update_fields=["assigned", "due_at"])
        audit.log(request, "tutorial.unassign", tutorial, user=person.pk, kept_progress=True)
        messages.success(request, f"“{tutorial.title}” is no longer assigned to {person.name}. "
                                  "What they have watched so far is kept.")
    else:
        row.delete()
        audit.log(request, "tutorial.unassign", tutorial, user=person.pk, kept_progress=False)
        messages.success(request, f"“{tutorial.title}” is no longer assigned to {person.name}.")
    return redirect_back(request, _employee_tab(person.pk, "tutorials"))


@require_POST
@permission_required_code("content.manage")
def progress_due(request, pk):
    row = _progress(request, pk)
    ok, value = _posted_due(request)
    if not ok:
        messages.error(request, "Enter a valid due date.")
    else:
        row.due_at = day_end(value)
        row.save(update_fields=["due_at"])
        audit.log(request, "tutorial.due_date", row.tutorial, user=row.user_id, due=value.isoformat() if value else None)
        messages.success(request, f"Due date for “{row.tutorial.title}” ({row.user.name}): {_due_label(value)}.")
    return redirect_back(request, _employee_tab(row.user_id, "tutorials"))


# ── Tests ───────────────────────────────────────────────────────────────────

def _assignment(request, pk):
    row = get_object_or_404(TestAssignment.objects.select_related("test__project", "user"), pk=pk)
    _check(request, row.test.project, row.user_id)
    return row


@require_POST
@permission_required_code("content.manage")
def test_assignment_unassign(request, pk):
    row = _assignment(request, pk)
    test, person = row.test, row.user
    row.delete()
    audit.log(request, "test.unassign", test, user=person.pk)
    messages.success(request, f"“{test.title}” is no longer assigned to {person.name}. Attempts already made are kept.")
    return redirect_back(request, _employee_tab(person.pk, "tests"))


@require_POST
@permission_required_code("content.manage")
def test_assignment_due(request, pk):
    row = _assignment(request, pk)
    ok, value = _posted_due(request)
    if not ok:
        messages.error(request, "Enter a valid due date.")
    else:
        row.due_at = day_end(value)
        row.save(update_fields=["due_at"])
        audit.log(request, "test.due_date", row.test, user=row.user_id, due=value.isoformat() if value else None)
        messages.success(request, f"Due date for “{row.test.title}” ({row.user.name}): {_due_label(value)}.")
    return redirect_back(request, _employee_tab(row.user_id, "tests"))


def _test_person(request, pk, user_pk):
    test = get_content(request, Test, pk, manage=True, select=("project",))
    person = get_object_or_404(employee_scope(request.user), pk=user_pk)
    return test, person


@require_POST
@permission_required_code("content.manage")
def test_reset_attempts(request, pk, user_pk):
    test, person = _test_person(request, pk, user_pk)
    deleted = reset_attempts(test, person)
    audit.log(request, "test.reset_attempts", test, user=person.pk, deleted=deleted)
    if deleted:
        notify(person, NotificationType.TEST, f"টেস্ট আবার দিতে পারবেন: {test.title}",
               "আপনার আগের চেষ্টাগুলো মুছে দেওয়া হয়েছে। এখন শুরু থেকে আবার টেস্টটি দিতে পারবেন।",
               reverse("portal:test_detail", args=[test.pk]))
        messages.success(request, f"Deleted {deleted} attempt(s) of {person.name} at “{test.title}”. They can start again from attempt 1.")
    else:
        messages.info(request, f"{person.name} has no attempts at “{test.title}” — nothing to reset.")
    return redirect_back(request, reverse("backoffice:test_results", args=[test.pk]))


@require_POST
@permission_required_code("content.manage")
def test_extra_attempt(request, pk, user_pk):
    test, person = _test_person(request, pk, user_pk)
    if test.attempt_limit is None:
        messages.info(request, f"“{test.title}” allows unlimited attempts — no extra attempt is needed.")
        return redirect_back(request, reverse("backoffice:test_results", args=[test.pk]))
    assignment = grant_extra_attempt(test, person, by=request.user)
    audit.log(request, "test.extra_attempt", test, user=person.pk, extra_attempts=assignment.extra_attempts)
    notify(person, NotificationType.TEST, f"আরও একবার চেষ্টা করতে পারবেন: {test.title}",
           "আপনাকে এই টেস্টে আরও একটি চেষ্টার সুযোগ দেওয়া হয়েছে।", reverse("portal:test_detail", args=[test.pk]))
    messages.success(request, f"{person.name} can now take “{test.title}” {test.attempt_limit + assignment.extra_attempts} "
                              f"time(s) in total ({assignment.extra_attempts} extra).")
    return redirect_back(request, reverse("backoffice:test_results", args=[test.pk]))


# ── Feedback ────────────────────────────────────────────────────────────────

@require_POST
@permission_required_code("content.manage")
def feedback_recipient_remove(request, pk):
    row = get_object_or_404(FeedbackRecipient.objects.select_related("feedback__project", "feedback__test", "user"), pk=pk)
    _check(request, row.feedback.project, row.user_id)
    fb, person = row.feedback, row.user
    row.delete()
    if fb.test_id:  # the linked test was assigned together with the feedback
        TestAssignment.objects.filter(test_id=fb.test_id, user=person).delete()
    audit.log(request, "feedback.recipient_remove", fb, user=person.pk)
    messages.success(request, f"{person.name} was removed from the recipients of {fb.display_number}. "
                              "They no longer see it in the portal.")
    return redirect_back(request, _employee_tab(person.pk, "feedback"))

