"""Training progress matrix and the employee report."""

from django.db.models import Prefetch, Q
from django.shortcuts import render

from apps.accounts.decorators import permission_required_code
from apps.accounts.models import Role, User, UserStatus
from apps.core.choices import ContentStatus, ProgressStatus
from apps.projects.models import ProjectMember
from apps.training.models import Tutorial, TutorialProgress
from apps.training.services import onboarding_matrix

from ..helpers import csv_response, employee_scope, paginate, pct, scope_ids, staff_projects, wants_csv
from ..stats import feedback_by_user, latest, tests_by_user, training_by_user


@permission_required_code("reports.view")
def training_progress(request):
    user = request.user
    projects = list(staff_projects(user).order_by("name"))
    f = {k: request.GET.get(k, "").strip() for k in ("project", "team", "q", "status")}
    project = None
    if f["project"].isdigit():
        project = next((p for p in projects if p.pk == int(f["project"])), None)
    elif f["project"] != "global" and projects:
        project = projects[0]
        f["project"] = str(project.pk)

    employees = employee_scope(user, User.objects.filter(role=Role.EMPLOYEE, status=UserStatus.ACTIVE))
    tutorials = Tutorial.objects.filter(status=ContentStatus.PUBLISHED, is_required=True).select_related("project")
    teams = []
    if project is not None:
        employees = employees.filter(memberships__project=project)
        tutorials = tutorials.filter(Q(project=project) | Q(project__isnull=True))
        teams = list(project.teams.all())
        if f["team"].isdigit():
            employees = employees.filter(memberships__project=project, memberships__team_id=int(f["team"]))
    else:
        tutorials = tutorials.filter(project__isnull=True)
    if f["q"]:
        employees = employees.filter(Q(name__icontains=f["q"]) | Q(employee_id__icontains=f["q"]) | Q(email__icontains=f["q"]))
    tutorials = list(tutorials.order_by("project_id", "published_at"))
    employees = employees.order_by("name")
    if project is not None:
        employees = employees.prefetch_related(Prefetch("memberships", queryset=ProjectMember.objects.filter(project=project).select_related("team"), to_attr="pm"))

    page = paginate(request, employees, 30)
    people = list(page)
    rows = {
        (p.user_id, p.tutorial_id): p
        for p in TutorialProgress.objects.filter(user__in=people, tutorial__in=tutorials).only(
            "user_id", "tutorial_id", "status", "percent", "completed_at", "assigned", "due_at")
    }
    onboarding = onboarding_matrix(project, people) if project is not None else {}
    col_stats = {t.pk: {"assigned": 0, "done": 0} for t in tutorials}
    matrix = []
    for person in people:
        cells, assigned, done = [], 0, 0
        for t in tutorials:
            p = rows.get((person.pk, t.pk))
            if p and p.assigned:
                assigned += 1
                col_stats[t.pk]["assigned"] += 1
                if p.status == ProgressStatus.COMPLETED:
                    done += 1
                    col_stats[t.pk]["done"] += 1
            cells.append({"tutorial": t, "p": p})
        matrix.append({
            "user": person, "cells": cells, "assigned": assigned, "done": done, "percent": pct(done, assigned),
            "member": person.pm[0] if project is not None and getattr(person, "pm", None) else None,
            "onboarding": onboarding.get(person.pk),
        })
    if f["status"] == "complete":
        matrix = [r for r in matrix if r["assigned"] and r["done"] == r["assigned"]]
    elif f["status"] == "incomplete":
        matrix = [r for r in matrix if r["done"] < r["assigned"]]
    columns = [{"tutorial": t, "assigned": col_stats[t.pk]["assigned"], "done": col_stats[t.pk]["done"],
                "percent": pct(col_stats[t.pk]["done"], col_stats[t.pk]["assigned"])} for t in tutorials]
    total_assigned = sum(c["assigned"] for c in columns)
    total_done = sum(c["done"] for c in columns)
    return render(request, "backoffice/training/progress.html", {
        "page_title": "Training progress",
        "page_subtitle": "Required tutorials per employee — completion is measured from real video playback.",
        "crumbs": [("Training progress", None)],
        "projects": projects,
        "project": project,
        "teams": teams,
        "filters": f,
        "columns": columns,
        "matrix": matrix,
        "page": page,
        "overall": pct(total_done, total_assigned),
        "total_done": total_done,
        "total_assigned": total_assigned,
    })


@permission_required_code("reports.view")
def reports(request):
    user = request.user
    projects = list(staff_projects(user).order_by("name"))
    f = {k: request.GET.get(k, "").strip() for k in ("project", "status", "q", "sort")}
    employees = employee_scope(user, User.objects.filter(role=Role.EMPLOYEE))
    project_ids = scope_ids(user)
    project = None
    if f["project"].isdigit():
        project = next((p for p in projects if p.pk == int(f["project"])), None)
        if project:
            employees = employees.filter(memberships__project=project)
            project_ids = [project.pk]
    if f["status"] in UserStatus.values:
        employees = employees.filter(status=f["status"])
    else:
        employees = employees.exclude(status=UserStatus.PENDING)
    if f["q"]:
        employees = employees.filter(Q(name__icontains=f["q"]) | Q(employee_id__icontains=f["q"]) | Q(email__icontains=f["q"]))
    member_qs = ProjectMember.objects.select_related("project")
    if scope_ids(user) is not None:
        member_qs = member_qs.filter(project_id__in=scope_ids(user))
    people = list(employees.prefetch_related(Prefetch("memberships", queryset=member_qs)).order_by("name"))
    ids = [p.pk for p in people]
    training = training_by_user(ids, project_ids)
    fb = feedback_by_user(ids, project_ids)
    tests = tests_by_user(ids, project_ids)
    rows = []
    for p in people:
        t = training.get(p.pk) or {"done": 0, "total": 0, "percent": None, "last": None}
        fstat = fb.get(p.pk) or {"received": 0, "watched": 0, "watched_pct": None, "tests_total": 0, "tests_passed": 0, "last": None}
        ts = tests.get(p.pk) or {"attempted": 0, "passed": 0, "attempts": 0, "avg": None, "last": None}
        rows.append({
            "user": p, "projects": [m.project for m in p.memberships.all()], "training": t, "feedback": fstat, "tests": ts,
            "last_activity": latest(p.last_login, t.get("last"), fstat.get("last"), ts.get("last")),
        })
    sorters = {
        "training": lambda r: (r["training"]["percent"] is None, -(r["training"]["percent"] or 0)),
        "training_asc": lambda r: (r["training"]["percent"] is None, r["training"]["percent"] or 0),
        "score": lambda r: (r["tests"]["avg"] is None, -(r["tests"]["avg"] or 0)),
        "feedback": lambda r: (r["feedback"]["watched_pct"] is None, r["feedback"]["watched_pct"] or 0),
        "activity": lambda r: (r["last_activity"] is None, -(r["last_activity"].timestamp() if r["last_activity"] else 0)),
    }
    if f["sort"] in sorters:
        rows.sort(key=sorters[f["sort"]])
    if wants_csv(request):
        return csv_response("employee-report", [
            "Employee", "Employee ID", "Email", "Status", "Projects", "Training completion %", "Required tutorials done",
            "Required tutorials total", "Feedback received", "Feedback watched", "Feedback watched %", "Feedback tests passed",
            "Feedback tests total", "Tests passed", "Tests attempted", "Attempts", "Average score %", "Last activity",
        ], (
            [r["user"].name, r["user"].employee_id, r["user"].email, r["user"].get_status_display(),
             ", ".join(p.code for p in r["projects"]), r["training"]["percent"], r["training"]["done"], r["training"]["total"],
             r["feedback"]["received"], r["feedback"]["watched"], r["feedback"]["watched_pct"], r["feedback"]["tests_passed"],
             r["feedback"]["tests_total"], r["tests"]["passed"], r["tests"]["attempted"], r["tests"]["attempts"],
             round(r["tests"]["avg"], 1) if r["tests"]["avg"] is not None else "", r["last_activity"]]
            for r in rows
        ))
    totals = {
        "employees": len(rows),
        "training": pct(sum(r["training"]["done"] for r in rows), sum(r["training"]["total"] for r in rows)),
        "feedback": pct(sum(r["feedback"]["watched"] for r in rows), sum(r["feedback"]["received"] for r in rows)),
        "avg": (lambda xs: sum(xs) / len(xs) if xs else None)([r["tests"]["avg"] for r in rows if r["tests"]["avg"] is not None]),
    }
    page = paginate(request, rows, 50)
    return render(request, "backoffice/reports/employees.html", {
        "page_title": "Reports",
        "page_subtitle": "Per-employee training, feedback and test performance.",
        "crumbs": [("Reports", None)],
        "projects": projects,
        "project": project,
        "filters": f,
        "page": page,
        "totals": totals,
        "statuses": UserStatus.choices,
    })
