from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.permissions import has_permission
from apps.core import audit
from apps.storage.services import delete_asset
from apps.website.models import ContactMessage, JobApplication, LeadStatus, QuoteRequest

from ..forms import MessageUpdateForm, QuoteUpdateForm
from ..helpers import csv_response, paginate, redirect_back, wants_csv

PIPELINE = [LeadStatus.NEW, LeadStatus.CONTACTED, LeadStatus.QUALIFIED, LeadStatus.PROPOSAL]
OUTCOMES = [LeadStatus.WON, LeadStatus.LOST, LeadStatus.ARCHIVED]


def _status_counts(model):
    return dict(model.objects.order_by().values_list("status").annotate(n=Count("pk")))


# ── Deleting website enquiries (super admins: "enquiries.delete") ───────────

# Uploaded files that belong only to the enquiry and are deleted with it (personal data).
ENQUIRY_FILES = {QuoteRequest: ("attachment",), ContactMessage: (), JobApplication: ("cv", "sample")}
ENQUIRY_EVENTS = {QuoteRequest: "lead.delete", ContactMessage: "message.delete", JobApplication: "applicant.delete"}


def delete_enquiries(request, objects, **meta) -> int:
    """Delete quote requests / contact messages / job applications and their uploaded files (one audit entry each)."""
    count = 0
    for obj in objects:
        model = type(obj)
        assets = [getattr(obj, f) for f in ENQUIRY_FILES[model] if getattr(obj, f"{f}_id")]
        name = getattr(obj, "full_name", None) or obj.name
        with transaction.atomic():
            audit.log(request, ENQUIRY_EVENTS[model], obj, name=name, email=obj.email, files=len(assets), **meta)
            obj.delete()
        for asset in assets:
            delete_asset(asset)
        count += 1
    return count


def posted_ids(request) -> list[int]:
    return [int(v) for v in request.POST.getlist("ids") if str(v).isdigit()][:500]


def bulk_delete(request, model, label, fallback):
    """POST ids=… from a list page → delete the selected enquiries."""
    ids = posted_ids(request)
    if not ids:
        messages.error(request, f"Select at least one {label} to delete.")
        return redirect_back(request, fallback)
    n = delete_enquiries(request, list(model.objects.filter(pk__in=ids)), bulk=True)
    messages.success(request, f"Deleted {n} {label}{'' if n == 1 else 's'}.")
    return redirect_back(request, fallback)


@require_POST
@permission_required_code("enquiries.delete")
def lead_delete(request, pk):
    lead = get_object_or_404(QuoteRequest, pk=pk)
    label = lead.company or lead.name
    delete_enquiries(request, [lead])
    messages.success(request, f"The quote request from {label} was deleted.")
    return redirect("backoffice:lead_list")


@require_POST
@permission_required_code("enquiries.delete")
def lead_bulk_delete(request):
    return bulk_delete(request, QuoteRequest, "quote request", reverse("backoffice:lead_list"))


@require_POST
@permission_required_code("enquiries.delete")
def message_delete(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    name = msg.name
    delete_enquiries(request, [msg])
    messages.success(request, f"The message from {name} was deleted.")
    return redirect("backoffice:message_list")


@require_POST
@permission_required_code("enquiries.delete")
def message_bulk_delete(request):
    return bulk_delete(request, ContactMessage, "message", reverse("backoffice:message_list"))


@permission_required_code("leads.manage")
def lead_list(request):
    qs = QuoteRequest.objects.select_related("attachment").order_by("-created_at")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(company__icontains=q) | Q(email__icontains=q) | Q(project_type__icontains=q))
    if status in LeadStatus.values:
        qs = qs.filter(status=status)
    if wants_csv(request):
        audit.log(request, "leads.export", None, count=qs.count())
        return csv_response("quote-requests", [
            "ID", "Received", "Name", "Company", "Email", "Phone", "Project type", "Annotation types", "Dataset size",
            "Timeline", "Platform", "Requirements", "Status", "Notes", "Source",
        ], (
            [r.pk, r.created_at, r.name, r.company, r.email, r.phone, r.project_type, ", ".join(r.annotation_types or []),
             r.dataset_size, r.timeline, r.platform, r.requirements, r.get_status_display(), r.notes, r.source]
            for r in qs.iterator()
        ))
    counts = _status_counts(QuoteRequest)
    return render(request, "backoffice/leads/list.html", {
        "page_title": "Quote requests",
        "page_subtitle": "Leads from the “Get a quote” form, from first contact to won or lost.",
        "crumbs": [("Quote requests", None)],
        "page": paginate(request, qs),
        "statuses": LeadStatus.choices,
        "counts": counts,
        "total": sum(counts.values()),
        "filters": {"q": q, "status": status},
        "can_delete": has_permission(request.user, "enquiries.delete"),
    })


@permission_required_code("leads.manage")
def lead_detail(request, pk):
    lead = get_object_or_404(QuoteRequest.objects.select_related("attachment"), pk=pk)
    form = QuoteUpdateForm(request.POST or None, instance=lead)
    if request.method == "POST":
        if form.is_valid():
            changed = form.changed_data
            form.save()
            audit.log(request, "lead.update", lead, fields=changed, status=lead.status)
            messages.success(request, "Lead updated.")
            return redirect("backoffice:lead_detail", pk=lead.pk)
        messages.error(request, "Please correct the errors below.")
    return render(request, "backoffice/leads/detail.html", {
        "page_title": None,
        "crumbs": [("Quote requests", reverse("backoffice:lead_list")), (lead.name, None)],
        "lead": lead,
        "form": form,
        "pipeline": [(s.value, s.label) for s in PIPELINE],
        "outcomes": [(s.value, s.label) for s in OUTCOMES],
        "stage_index": PIPELINE.index(lead.status) if lead.status in PIPELINE else len(PIPELINE),
        "can_delete": has_permission(request.user, "enquiries.delete"),
    })


@permission_required_code("leads.manage")
def message_list(request):
    qs = ContactMessage.objects.order_by("-created_at")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(company__icontains=q) | Q(subject__icontains=q) | Q(message__icontains=q))
    if status in LeadStatus.values:
        qs = qs.filter(status=status)
    if wants_csv(request):
        audit.log(request, "messages.export", None, count=qs.count())
        return csv_response("contact-messages", ["ID", "Received", "Name", "Email", "Company", "Phone", "Subject", "Message", "Status", "Notes"], (
            [m.pk, m.created_at, m.name, m.email, m.company, m.phone, m.subject, m.message, m.get_status_display(), m.notes]
            for m in qs.iterator()
        ))
    counts = _status_counts(ContactMessage)
    return render(request, "backoffice/leads/messages.html", {
        "page_title": "Messages",
        "page_subtitle": "Messages from the website contact form.",
        "crumbs": [("Messages", None)],
        "page": paginate(request, qs),
        "statuses": LeadStatus.choices,
        "counts": counts,
        "total": sum(counts.values()),
        "filters": {"q": q, "status": status},
        "can_delete": has_permission(request.user, "enquiries.delete"),
    })


@permission_required_code("leads.manage")
def message_detail(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    form = MessageUpdateForm(request.POST or None, instance=msg)
    if request.method == "POST":
        if form.is_valid():
            changed = form.changed_data
            form.save()
            audit.log(request, "message.update", msg, fields=changed, status=msg.status)
            messages.success(request, "Message updated.")
            return redirect("backoffice:message_detail", pk=msg.pk)
        messages.error(request, "Please correct the errors below.")
    return render(request, "backoffice/leads/message_detail.html", {
        "page_title": None,
        "crumbs": [("Messages", reverse("backoffice:message_list")), (msg.name, None)],
        "msg": msg,
        "form": form,
        "can_delete": has_permission(request.user, "enquiries.delete"),
    })
