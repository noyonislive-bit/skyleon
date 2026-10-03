from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.services import convert_application
from apps.core import audit
from apps.website.models import ApplicationStatus, JobApplication

from ..forms import ApplicationUpdateForm
from ..helpers import paginate


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
    return render(request, "backoffice/applicants/detail.html", {
        "page_title": None,
        "crumbs": [("Applicants", reverse("backoffice:applicant_list")), (app.full_name, None)],
        "app": app,
        "form": form,
        "pipeline": [c for c in ApplicationStatus.choices],
    })


@require_POST
@permission_required_code("applicants.manage")
def applicant_convert(request, pk):
    app = get_object_or_404(JobApplication, pk=pk)
    if app.user_id:
        messages.info(request, "This applicant already has an account.")
        return redirect("backoffice:employee_detail", pk=app.user_id)
    user = convert_application(app, request.user)
    audit.log(request, "applicant.convert", app, user=user.pk)
    messages.success(request, f"{user.name} is now an employee ({user.employee_id}). A password-setup email has been sent.")
    return redirect("backoffice:employee_detail", pk=user.pk)
