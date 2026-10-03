"""
Shared helpers for the admin panel: scoping, object lookups, pagination,
safe redirects and CSV export.

Scoping rules (on top of the permission codes in accounts.permissions):
  * Super admins see everything.
  * Project managers / trainers see the projects they are members of
    (`project_scope`, `can_manage_project`, `can_manage_content_for`).
  * Employees visible to a scoped staff member are the employees of their
    projects. Staff who may manage employees (project managers) additionally
    see the unassigned pool (pending signups and employees without a project),
    so they can approve them and staff their projects.
"""

import csv
import math
from datetime import datetime, time

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.models import Role, User, UserStatus
from apps.accounts.permissions import (
    can_manage_content_for,
    can_manage_project,
    has_permission,
    is_unscoped,
    project_scope,
    scoped_project_ids,
)
from apps.projects.models import Project, ProjectMember

PER_PAGE = 25


# ── Scope ───────────────────────────────────────────────────────────────────

def scope_ids(user):
    """Cached per request-user: None (all projects) or list of project ids."""
    if not hasattr(user, "_bo_scope_ids"):
        user._bo_scope_ids = scoped_project_ids(user)
    return user._bo_scope_ids


def staff_projects(user):
    ids = scope_ids(user)
    qs = Project.objects.all()
    return qs if ids is None else qs.filter(pk__in=ids)


def employee_scope(user, qs=None):
    """Users (accounts) the staff member may see in the people area."""
    qs = User.objects.all() if qs is None else qs
    if is_unscoped(user):
        return qs
    ids = scope_ids(user) or []
    in_projects = Exists(ProjectMember.objects.filter(user=OuterRef("pk"), project_id__in=ids))
    cond = in_projects
    if has_permission(user, "employees.manage"):
        cond = in_projects | ~Exists(ProjectMember.objects.filter(user=OuterRef("pk")))
    return qs.filter(role=Role.EMPLOYEE).filter(cond)


def assignable_people(user):
    """Active accounts a staff member may add to a project / invite / assign content to."""
    qs = User.objects.filter(status=UserStatus.ACTIVE)
    if is_unscoped(user):
        return qs.filter(role__in=[Role.EMPLOYEE, Role.PROJECT_MANAGER, Role.TRAINER])
    return employee_scope(user, qs)


def assignable_employees(user):
    return employee_scope(user, User.objects.filter(status=UserStatus.ACTIVE, role=Role.EMPLOYEE))


def can_manage_employee(user, target) -> bool:
    if not has_permission(user, "employees.manage") or target.pk == user.pk:
        return False
    if target.role != Role.EMPLOYEE:
        return has_permission(user, "staff.manage")
    return True


def can_edit_content(user, project_id) -> bool:
    """can_manage_content_for() by project id, using the per-request cached scope (no query per table row)."""
    if project_id is None:
        return can_manage_content_for(user, None)
    if not has_permission(user, "content.manage"):
        return False
    ids = scope_ids(user)
    return ids is None or project_id in ids


def people_q(user, prefix="user"):
    """Q() limiting rows (progress, attempts, assignments …) to the people the viewer may see — the
    same scope as the employee pages and the per-item tracking tables. Empty for super admins."""
    if is_unscoped(user):
        return Q()
    return Q(**{f"{prefix}__in": employee_scope(user)})


def can_target_project(user, project) -> bool:
    """Announcements / meetings: company-wide only for unscoped staff, otherwise own projects."""
    if project is None:
        return is_unscoped(user)
    ids = scope_ids(user)
    return ids is None or project.pk in ids


# ── Lookups ─────────────────────────────────────────────────────────────────

def get_employee(request, pk):
    return get_object_or_404(employee_scope(request.user), pk=pk)


def get_project(request, pk, *, manage=False):
    project = get_object_or_404(Project, pk=pk)
    if not can_manage_project(request.user, project):
        raise Http404
    if manage and not has_permission(request.user, "projects.manage"):
        raise PermissionDenied
    return project


def get_content(request, model, pk, *, manage=False, field="project", select=()):
    qs = model.objects.select_related(*select) if select else model.objects.all()
    obj = get_object_or_404(project_scope(qs, request.user, field=field), pk=pk)
    if manage:
        project = obj
        for part in field.split("__"):
            project = getattr(project, part) if project is not None else None
        if not can_manage_content_for(request.user, project):
            raise PermissionDenied
    return obj


# ── Requests / responses ────────────────────────────────────────────────────

def paginate(request, qs, per_page=PER_PAGE):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


def safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return fallback


def redirect_back(request, fallback):
    return redirect(safe_next(request, fallback))


def portal_link(name, *args):
    """Link into the employee portal; falls back to the portal home if the page does not exist (yet)."""
    try:
        return reverse(f"portal:{name}", args=args)
    except NoReverseMatch:
        return reverse("portal:dashboard")


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def day_start(d):
    return timezone.make_aware(datetime.combine(d, time.min)) if d else None


def day_end(d):
    return timezone.make_aware(datetime.combine(d, time.max)) if d else None


def parse_float(value):
    """A finite float from a query-string value, else None (rejects "nan", "inf", junk)."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def int_or_none(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def wants_csv(request):
    return request.GET.get("format") == "csv"


_CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        value = timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if timezone.is_aware(value) else value.strftime("%Y-%m-%d %H:%M")
    text = str(value)
    if text.startswith(_CSV_DANGEROUS):
        try:
            float(text)
        except ValueError:
            text = "'" + text  # neutralise spreadsheet formula injection
    return text


def csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    stamp = timezone.localdate().strftime("%Y%m%d")
    response["Content-Disposition"] = f'attachment; filename="{filename}-{stamp}.csv"'
    response.write("﻿")  # Excel-friendly UTF-8
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_cell(c) for c in row])
    return response


def pct(part, whole):
    return round(part / whole * 100) if whole else None
