from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.decorators import permission_required_code
from apps.core import audit
from apps.website.models import ContactMessage, LeadStatus, QuoteRequest

from ..forms import MessageUpdateForm, QuoteUpdateForm
from ..helpers import csv_response, paginate, wants_csv

PIPELINE = [LeadStatus.NEW, LeadStatus.CONTACTED, LeadStatus.QUALIFIED, LeadStatus.PROPOSAL]
OUTCOMES = [LeadStatus.WON, LeadStatus.LOST, LeadStatus.ARCHIVED]


def _status_counts(model):
    return dict(model.objects.order_by().values_list("status").annotate(n=Count("pk")))


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
        return csv_response("contact-messages", ["ID", "Received", "Name", "Email", "Company", "Phone", "Subject", "Message", "Status"], (
            [m.pk, m.created_at, m.name, m.email, m.company, m.phone, m.subject, m.message, m.get_status_display()] for m in qs.iterator()
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
    })


@permission_required_code("leads.manage")
def message_detail(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    form = MessageUpdateForm(request.POST or None, instance=msg)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request, "message.update", msg, status=msg.status)
        messages.success(request, "Message status updated.")
        return redirect("backoffice:message_detail", pk=msg.pk)
    return render(request, "backoffice/leads/message_detail.html", {
        "page_title": None,
        "crumbs": [("Messages", reverse("backoffice:message_list")), (msg.name, None)],
        "msg": msg,
        "form": form,
    })
