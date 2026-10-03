"""Announcements, meetings and the email log."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import formats, timezone, translation
from django.views.decorators.http import require_POST

from apps.accounts.decorators import permission_required_code
from apps.accounts.permissions import project_scope
from apps.comms.models import Announcement, EmailMessage, EmailStatus, Meeting, MeetingInvite, NotificationType
from apps.comms.services import deliver, notify
from apps.core import audit
from apps.core.audience import active_employees, project_audience

from ..forms import AnnouncementForm, MeetingForm
from ..helpers import can_target_project, paginate, portal_link, staff_projects


def _excerpt(text, n=180):
    text = " ".join((text or "").replace("#", "").replace("*", "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ── Announcements ───────────────────────────────────────────────────────────

@permission_required_code("announcements.manage")
def announcement_list(request):
    user = request.user
    qs = project_scope(Announcement.objects.all(), user).select_related("project", "created_by").annotate(read_count=Count("reads"))
    project = request.GET.get("project", "")
    if project == "global":
        qs = qs.filter(project__isnull=True)
    elif project.isdigit():
        qs = qs.filter(project_id=int(project))
    page = paginate(request, qs.order_by("-pinned", "-published_at"))
    everyone = active_employees().count()
    audience = {p.pk: p.n for p in staff_projects(user).annotate(n=Count("members", filter=Q(members__user__role="employee", members__user__status="active")))}
    for a in page:
        a.audience_size = audience.get(a.project_id, 0) if a.project_id else everyone
        a.can_edit = can_target_project(user, a.project)
    return render(request, "backoffice/comms/announcements.html", {
        "page_title": "Announcements",
        "page_subtitle": "News for everyone or for one project — shown in the portal, optionally emailed.",
        "crumbs": [("Announcements", None)],
        "page": page,
        "projects": staff_projects(user).order_by("name"),
        "filters": {"project": project},
    })


def _announcement_form(request, announcement=None):
    form = AnnouncementForm(request.POST or None, instance=announcement, user=request.user)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if announcement is None:
            obj.created_by = request.user
        obj.save()
        if announcement is None:
            audience = list(project_audience(obj.project) if obj.project_id else active_employees())
            email = form.cleaned_data.get("send_email")
            notify(
                audience, NotificationType.ANNOUNCEMENT, obj.title, _excerpt(obj.body), portal_link("announcements"),
                email_template="announcement" if email else None, email_subject=obj.title, context={"announcement": obj},
            )
            audit.log(request, "announcement.create", obj, recipients=len(audience), email=bool(email))
            messages.success(request, f"Announcement published to {len(audience)} employee(s)" + (" and emailed." if email else "."))
        else:
            audit.log(request, "announcement.edit", obj)
            messages.success(request, "Announcement updated.")
        return redirect("backoffice:announcement_list")
    return render(request, "backoffice/comms/announcement_form.html", {
        "page_title": "Edit announcement" if announcement else "New announcement",
        "crumbs": [("Announcements", reverse("backoffice:announcement_list")), ("Edit" if announcement else "New", None)],
        "form": form,
        "announcement": announcement,
    })


def _get_announcement(request, pk):
    obj = get_object_or_404(project_scope(Announcement.objects.select_related("project"), request.user), pk=pk)
    if not can_target_project(request.user, obj.project):
        raise PermissionDenied
    return obj


@permission_required_code("announcements.manage")
def announcement_create(request):
    return _announcement_form(request)


@permission_required_code("announcements.manage")
def announcement_edit(request, pk):
    return _announcement_form(request, _get_announcement(request, pk))


@require_POST
@permission_required_code("announcements.manage")
def announcement_delete(request, pk):
    obj = _get_announcement(request, pk)
    audit.log(request, "announcement.delete", obj, title=obj.title)
    obj.delete()
    messages.success(request, "Announcement deleted.")
    return redirect("backoffice:announcement_list")


# ── Meetings ────────────────────────────────────────────────────────────────

@permission_required_code("meetings.manage")
def meeting_list(request):
    user = request.user
    now = timezone.now()
    when = "past" if request.GET.get("when") == "past" else "upcoming"
    qs = project_scope(Meeting.objects.all(), user).select_related("project", "created_by").annotate(invitee_count=Count("invites"))
    if when == "past":
        qs = qs.filter(starts_at__lt=now).order_by("-starts_at")
    else:
        qs = qs.filter(starts_at__gte=now - timezone.timedelta(hours=3)).order_by("starts_at")
    page = paginate(request, qs)
    for m in page:
        m.can_edit = can_target_project(user, m.project) or m.created_by_id == user.pk
        m.ends_at = m.starts_at + timezone.timedelta(minutes=m.duration_min)
        m.live = m.starts_at <= now <= m.ends_at
    return render(request, "backoffice/comms/meetings.html", {
        "page_title": "Meetings",
        "page_subtitle": "Calibration calls, trainings and team meetings with Meet / Zoom / Teams links.",
        "crumbs": [("Meetings", None)],
        "page": page,
        "when": when,
    })


def _get_meeting(request, pk, manage=False):
    meeting = get_object_or_404(project_scope(Meeting.objects.select_related("project", "created_by"), request.user), pk=pk)
    if manage and not (can_target_project(request.user, meeting.project) or meeting.created_by_id == request.user.pk):
        raise PermissionDenied
    return meeting


def _meeting_people(form):
    d = form.cleaned_data
    if d["audience"] == MeetingForm.AUDIENCE_PROJECT:
        return list(project_audience(d["project"]) if d.get("project") else active_employees())
    return list(d["invitees"])


def _when(m):
    """Meeting time for employee notifications (the portal is in Bangla)."""
    with translation.override("bn"):
        when = formats.date_format(timezone.localtime(m.starts_at), "l, j F Y, H:i")
    return f"{when} · {m.duration_min} মিনিট"


def _meeting_form(request, meeting=None):
    form = MeetingForm(request.POST or None, instance=meeting, user=request.user)
    if request.method == "POST" and form.is_valid():
        before = (meeting.starts_at, meeting.meeting_url, meeting.duration_min) if meeting else None
        obj = form.save(commit=False)
        if meeting is None:
            obj.created_by = request.user
        obj.save()
        people = _meeting_people(form)
        existing = set(MeetingInvite.objects.filter(meeting=obj).values_list("user_id", flat=True))
        wanted = {u.pk for u in people}
        new_people = [u for u in people if u.pk not in existing]
        MeetingInvite.objects.bulk_create([MeetingInvite(meeting=obj, user=u) for u in new_people], ignore_conflicts=True)
        removed = existing - wanted
        if removed:
            MeetingInvite.objects.filter(meeting=obj, user_id__in=removed).delete()
        link = portal_link("meetings")
        notify(new_people, NotificationType.MEETING, f"মিটিং: {obj.title}", _when(obj), link,
               email_template="meeting_invite", email_subject=f"মিটিংয়ের আমন্ত্রণ: {obj.title}", context={"meeting": obj})
        changed = before is not None and before != (obj.starts_at, obj.meeting_url, obj.duration_min)
        if changed:
            kept = [u for u in people if u.pk in existing]
            notify(kept, NotificationType.MEETING, f"মিটিং পরিবর্তন: {obj.title}", _when(obj), link,
                   email_template="meeting_invite", email_subject=f"মিটিংয়ের সময়/লিংক বদলেছে: {obj.title}", context={"meeting": obj})
        audit.log(request, "meeting.edit" if meeting else "meeting.create", obj, invited=len(new_people), removed=len(removed))
        msg = f"Meeting saved — {len(new_people)} new invitation(s) sent"
        if changed:
            msg += ", existing invitees were told about the change"
        messages.success(request, msg + ".")
        return redirect("backoffice:meeting_detail", pk=obj.pk)
    return render(request, "backoffice/comms/meeting_form.html", {
        "page_title": "Edit meeting" if meeting else "Schedule a meeting",
        "page_subtitle": f"Times are in {timezone.get_current_timezone_name()}.",
        "crumbs": [("Meetings", reverse("backoffice:meeting_list")), ("Edit" if meeting else "New", None)],
        "form": form,
        "meeting": meeting,
    })


@permission_required_code("meetings.manage")
def meeting_create(request):
    return _meeting_form(request)


@permission_required_code("meetings.manage")
def meeting_edit(request, pk):
    return _meeting_form(request, _get_meeting(request, pk, manage=True))


@permission_required_code("meetings.manage")
def meeting_detail(request, pk):
    meeting = _get_meeting(request, pk)
    invites = list(meeting.invites.select_related("user").order_by("user__name"))
    return render(request, "backoffice/comms/meeting_detail.html", {
        "page_title": None,
        "crumbs": [("Meetings", reverse("backoffice:meeting_list")), (meeting.title, None)],
        "meeting": meeting,
        "ends_at": meeting.starts_at + timezone.timedelta(minutes=meeting.duration_min),
        "invites": invites,
        "is_past": meeting.starts_at < timezone.now(),
        "can_edit": can_target_project(request.user, meeting.project) or meeting.created_by_id == request.user.pk,
    })


@require_POST
@permission_required_code("meetings.manage")
def meeting_cancel(request, pk):
    meeting = _get_meeting(request, pk, manage=True)
    people = [i.user for i in meeting.invites.select_related("user")]
    if meeting.starts_at > timezone.now():
        notify(people, NotificationType.MEETING, f"মিটিং বাতিল: {meeting.title}",
               f"{_when(meeting)} সময়ের মিটিংটি বাতিল করা হয়েছে।", portal_link("dashboard"))
    audit.log(request, "meeting.cancel", meeting, title=meeting.title, invitees=len(people))
    meeting.delete()
    messages.success(request, f"Meeting cancelled — {len(people)} invitee(s) were notified.")
    return redirect("backoffice:meeting_list")


# ── Email log ───────────────────────────────────────────────────────────────

@permission_required_code("emails.view")
def email_list(request):
    qs = EmailMessage.objects.defer("html", "text").order_by("-created_at")
    f = {k: request.GET.get(k, "").strip() for k in ("q", "status", "template")}
    if f["q"]:
        qs = qs.filter(Q(to__icontains=f["q"]) | Q(subject__icontains=f["q"]))
    if f["status"] in EmailStatus.values:
        qs = qs.filter(status=f["status"])
    if f["template"]:
        qs = qs.filter(template=f["template"])
    counts = dict(EmailMessage.objects.order_by().values_list("status").annotate(n=Count("pk")))
    return render(request, "backoffice/comms/emails.html", {
        "page_title": "Email log",
        "page_subtitle": "Every email goes through this outbox. Failed or pending emails are retried by the cron job.",
        "crumbs": [("Email log", None)],
        "page": paginate(request, qs, 50),
        "filters": f,
        "statuses": EmailStatus.choices,
        "templates": EmailMessage.objects.order_by("template").values_list("template", flat=True).distinct(),
        "counts": counts,
        "retry_count": counts.get(EmailStatus.FAILED, 0) + counts.get(EmailStatus.PENDING, 0),
    })


@permission_required_code("emails.view")
def email_detail(request, pk):
    email = get_object_or_404(EmailMessage, pk=pk)
    return render(request, "backoffice/comms/email_detail.html", {
        "page_title": None,
        "crumbs": [("Email log", reverse("backoffice:email_list")), (f"#{email.pk}", None)],
        "email": email,
    })


@require_POST
@permission_required_code("emails.view")
def email_retry(request):
    pk = request.POST.get("pk")
    qs = EmailMessage.objects.exclude(status=EmailStatus.SENT)
    if pk and pk.isdigit():
        qs = qs.filter(pk=int(pk))
    ids = list(qs.values_list("pk", flat=True)[:200])
    if not ids:
        messages.info(request, "There are no failed or pending emails to retry.")
        return redirect("backoffice:email_list")
    EmailMessage.objects.filter(pk__in=ids, status=EmailStatus.FAILED).update(status=EmailStatus.PENDING, attempts=0)
    sent, failed = deliver(ids, limit=200)
    audit.log(request, "email.retry", None, ids=ids[:50], sent=sent, failed=failed)
    if failed:
        messages.warning(request, f"{sent} email(s) sent, {failed} still failing — check the error column and the SMTP settings.")
    else:
        messages.success(request, f"{sent} email(s) sent.")
    return redirect(reverse("backoffice:email_detail", args=[int(pk)]) if pk and pk.isdigit() else reverse("backoffice:email_list"))
