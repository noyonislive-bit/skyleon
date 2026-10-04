"""
Client organisations and client portal accounts (super admins: "clients.manage").

An organisation groups client accounts (role Client) and the projects run for that client; client
accounts see the organisation's projects in the client portal (/client/). Client accounts are
suspended / reactivated / deleted / sent a password link with the same actions as employee accounts.
"""

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.models import Organization, Role, User
from apps.accounts.services import create_client
from apps.core import audit
from apps.projects.models import Project

from ..forms import ClientCreateForm, ClientEditForm, LinkProjectForm, OrganizationForm

PERM = "clients.manage"


def _org_crumbs(org=None, *extra):
    crumbs = [("Clients", reverse("backoffice:organization_list"))]
    if org is not None:
        crumbs.append((org.name, reverse("backoffice:organization_detail", args=[org.pk])))
    return crumbs + list(extra)


@permission_required_code(PERM)
def organization_list(request):
    q = request.GET.get("q", "").strip()
    qs = Organization.objects.annotate(
        client_count=Count("users", filter=Q(users__role=Role.CLIENT), distinct=True),
        other_count=Count("users", filter=~Q(users__role=Role.CLIENT), distinct=True),
        project_count=Count("projects", distinct=True),
    ).order_by("name")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(contact_email__icontains=q) | Q(users__email__icontains=q)
                       | Q(users__name__icontains=q)).distinct()
    unattached = User.objects.filter(role=Role.CLIENT, organization__isnull=True).order_by("name")
    return render(request, "backoffice/clients/organizations.html", {
        "page_title": "Clients",
        "page_subtitle": "Client organisations, their client-portal accounts and the projects they can see.",
        "crumbs": [("Clients", None)],
        "organizations": list(qs),
        "unattached": list(unattached),
        "filters": {"q": q},
    })


def _organization_form(request, org=None):
    form = OrganizationForm(request.POST or None, instance=org)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        audit.log(request, "organization.edit" if org else "organization.create", obj, name=obj.name)
        messages.success(request, "Organisation saved." if org else f"Organisation “{obj.name}” created. Next: add its client accounts.")
        return redirect("backoffice:organization_detail", pk=obj.pk)
    return render(request, "backoffice/clients/organization_form.html", {
        "page_title": f"Edit {org.name}" if org else "New organisation",
        "crumbs": _org_crumbs(org, ("Edit" if org else "New organisation", None)),
        "form": form,
        "org": org,
    })


@permission_required_code(PERM)
def organization_create(request):
    return _organization_form(request)


@permission_required_code(PERM)
def organization_edit(request, pk):
    return _organization_form(request, get_object_or_404(Organization, pk=pk))


@permission_required_code(PERM)
def organization_detail(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    clients = list(org.users.filter(role=Role.CLIENT).order_by("name"))
    others = list(org.users.exclude(role=Role.CLIENT).order_by("name"))  # e.g. a client account that became staff
    projects = list(org.projects.order_by("status", "name"))
    return render(request, "backoffice/clients/organization_detail.html", {
        "page_title": None,
        "crumbs": _org_crumbs(None, (org.name, None)),
        "org": org,
        "clients": clients,
        "others": others,
        "projects": projects,
        "link_form": LinkProjectForm(organization=org),
        "can_delete": not clients and not others and not projects,
    })


@require_POST
@permission_required_code(PERM)
def organization_delete(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    users, projects = org.users.count(), org.projects.count()
    if users or projects:
        parts = []
        if users:
            parts.append(f"{users} account{'s' if users != 1 else ''}")
        if projects:
            parts.append(f"{projects} project{'s' if projects != 1 else ''}")
        messages.error(request, f"“{org.name}” still has {' and '.join(parts)}. Move or delete the client accounts and "
                                "unlink the projects first — then the organisation can be deleted.")
        return redirect("backoffice:organization_detail", pk=org.pk)
    name = org.name
    audit.log(request, "organization.delete", org, name=name)
    org.delete()
    messages.success(request, f"Organisation “{name}” deleted.")
    return redirect("backoffice:organization_list")


@require_POST
@permission_required_code(PERM)
def organization_projects(request, pk):
    """Link a project to the organisation (its clients then see it) or unlink one."""
    org = get_object_or_404(Organization, pk=pk)
    if request.POST.get("action") == "unlink":
        project = get_object_or_404(Project, pk=request.POST.get("project") or 0, organization=org)
        project.organization = None
        project.save(update_fields=["organization", "updated_at"])
        audit.log(request, "organization.project_unlink", org, project=project.code)
        messages.success(request, f"{project.code} is no longer linked to {org.name}. Its clients can't see it any more.")
    else:
        form = LinkProjectForm(request.POST, organization=org)
        if form.is_valid():
            project = form.cleaned_data["project"]
            previous = project.organization
            project.organization = org
            project.save(update_fields=["organization", "updated_at"])
            audit.log(request, "organization.project_link", org, project=project.code,
                      previous=previous.name if previous else None)
            messages.success(request, f"{project.code} is now linked to {org.name} — its client accounts can see it.")
        else:
            messages.error(request, "Choose a project to link.")
    return redirect("backoffice:organization_detail", pk=org.pk)


# ── Client accounts ─────────────────────────────────────────────────────────

@permission_required_code(PERM)
def client_create(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    form = ClientCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        client = create_client(email=d["email"], name=d["name"], organization=org, invited_by=request.user,
                               send_invite=d["send_invite"], phone=d.get("phone", ""), title=d.get("title", ""))
        audit.log(request, "client.create", client, organization=org.pk, invited=d["send_invite"])
        messages.success(request, f"Client account for {client.name} created."
                         + (" A password-setup email (in English) is on its way." if d["send_invite"] else
                            " Use “Send password link” when they should get access."))
        return redirect("backoffice:organization_detail", pk=org.pk)
    return render(request, "backoffice/clients/client_form.html", {
        "page_title": "Add client account",
        "page_subtitle": f"The account can sign in to the client portal and sees the projects linked to {org.name}.",
        "crumbs": _org_crumbs(org, ("Add client account", None)),
        "form": form,
        "org": org,
        "creating": True,
    })


@permission_required_code(PERM)
def client_edit(request, pk):
    client = get_object_or_404(User, pk=pk, role=Role.CLIENT)
    form = ClientEditForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid():
        old_org = client.organization_id
        changed = list(form.changed_data)
        form.save()
        audit.log(request, "client.edit", client, fields=changed, organization=client.organization_id,
                  previous_organization=old_org if "organization" in changed else None)
        messages.success(request, f"{client.name} saved.")
        return redirect("backoffice:organization_detail", pk=client.organization_id)
    org = client.organization
    return render(request, "backoffice/clients/client_form.html", {
        "page_title": f"Edit {client.name}",
        "crumbs": _org_crumbs(org, (client.name, None)) if org else [("Clients", reverse("backoffice:organization_list")), (client.name, None)],
        "form": form,
        "org": org,
        "client": client,
    })

