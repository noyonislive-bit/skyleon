from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.permissions import has_permission
from apps.accounts.services import ConversionRefused, application_account, conversion_problem, convert_application
from apps.core import audit
from apps.website.models import ApplicationStatus, JobApplication

from ..forms import ApplicationUpdateForm
from ..helpers import employee_scope, paginate


def _can_see(user, account):
    """May the viewer open this account's employee page?"""
    return (account is not None and has_permission(user, "employees.view")
            and employee_scope(user).filter(pk=account.pk).exists())


@permission_required_code("applicants.manage")
def applicant_list(request):
    qs = JobApplication.objects.select_related("user", "cv").order_by("-created_at")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(location__icontains=q) | Q(phone__icontains=q))
    if status in ApplicationStatus.values:
        qs = qs.filter(status=status)
    counts = dict(JobApplication.objects.order_by().values_list("status").annotate(n=Count("pk")))
    return render(request, "backoffice/applicants/list.html", {
        "page_title": "Applicants",
        "page_subtitle": "Careers applications from the public website.",
        "crumbs": [("Applicants", None)],
        "page": paginate(request, qs),
        "statuses": ApplicationStatus.choices,
        "counts": counts,
        "total": sum(counts.values()),
        "filters": {"q": q, "status": status},
    })


@permission_required_code("applicants.manage")
def applicant_detail(request, pk):
    app = get_object_or_404(JobApplication.objects.select_related("user", "cv", "sample"), pk=pk)
    form = ApplicationUpdateForm(request.POST or None, instance=app)
    if request.method == "POST":
        if form.is_valid():
            changed = form.changed_data
            form.save()
            audit.log(request, "applicant.update", app, fields=changed, status=app.status)
            messages.success(request, "Application updated.")
            return redirect("backoffice:applicant_detail", pk=app.pk)
        messages.error(request, "Please correct the errors below.")
    existing = None if app.user_id else application_account(app)
    return render(request, "backoffice/applicants/detail.html", {
        "page_title": None,
        "crumbs": [("Applicants", reverse("backoffice:applicant_list")), (app.full_name, None)],
        "app": app,
        "form": form,
        "pipeline": [c for c in ApplicationStatus.choices],
        "linked_visible": _can_see(request.user, app.user) if app.user_id else False,
        "existing": existing,
        "existing_visible": _can_see(request.user, existing),
        "existing_problem": conversion_problem(existing) if existing else None,
    })


@require_POST
@permission_required_code("applicants.manage")
def applicant_convert(request, pk):
    app = get_object_or_404(JobApplication, pk=pk)
    if app.user_id:
        messages.info(request, "This applicant already has an account.")
        if _can_see(request.user, app.user):
            return redirect("backoffice:employee_detail", pk=app.user_id)
        return redirect("backoffice:applicant_detail", pk=app.pk)
    try:
        result = convert_application(app, request.user)
    except ConversionRefused as exc:
        messages.error(request, str(exc))
        return redirect("backoffice:applicant_detail", pk=app.pk)
    user = result.user
    audit.log(request, "applicant.convert", app, user=user.pk, created=result.created, invited=result.invited)
    if result.created:
        msg = f"{user.name} is now an employee ({user.employee_id})."
        if result.invited:
            msg += " A password-setup email has been sent."
    else:
        msg = (f"The application is now linked to the existing account of {user.name} "
               f"({user.get_role_display()} · {user.get_status_display()}). The account was not changed and no email was sent.")
    messages.success(request, msg)
    if _can_see(request.user, user):
        return redirect("backoffice:employee_detail", pk=user.pk)
    return redirect("backoffice:applicant_detail", pk=app.pk)
