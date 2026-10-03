from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.comms.models import AnnouncementRead, Meeting, Notification, NotificationType

from ..helpers import crumbs, paginate, safe_internal_path
from ..scope import portal_api, portal_view
from .dashboard import upcoming_meetings

NOTIFICATION_ICONS = {
    NotificationType.TRAINING: ("graduation-cap", "bg-brand-50 text-brand-600 ring-brand-100"),
    NotificationType.FEEDBACK: ("message-square-warning", "bg-amber-50 text-amber-600 ring-amber-100"),
    NotificationType.TEST: ("clipboard-check", "bg-violet-50 text-violet-600 ring-violet-100"),
    NotificationType.ANNOUNCEMENT: ("megaphone", "bg-sky-50 text-sky-600 ring-sky-100"),
    NotificationType.MEETING: ("calendar-clock", "bg-cyan-50 text-cyan-600 ring-cyan-100"),
    NotificationType.ACCOUNT: ("user-check", "bg-emerald-50 text-emerald-600 ring-emerald-100"),
    NotificationType.PROJECT: ("briefcase", "bg-indigo-50 text-indigo-600 ring-indigo-100"),
    NotificationType.SYSTEM: ("info", "bg-slate-100 text-slate-600 ring-slate-200"),
}


def decorate_notifications(items):
    for n in items:
        n.icon_name, n.icon_class = NOTIFICATION_ICONS.get(n.ntype, NOTIFICATION_ICONS[NotificationType.SYSTEM])
    return items


# ── Announcements ────────────────────────────────────────────────────────────

def _mark_announcement_read(announcement, user):
    AnnouncementRead.objects.get_or_create(announcement=announcement, user=user)


@portal_view
def announcements(request):
    scope = request.portal
    qs = scope.announcements().select_related("project", "created_by").annotate(is_read=scope.announcement_read())
    show = request.GET.get("show")
    if show == "unread":
        qs = qs.filter(is_read=False)
    page = paginate(request, qs, 15)
    return render(request, "portal/announcements.html", {
        "page": page,
        "show": show,
        "page_title": "Announcements",
        "page_subtitle": "Company-wide news and updates from your project teams.",
        "crumbs": crumbs(("Announcements", None)),
    })


@portal_view
def announcement_detail(request, pk):
    scope = request.portal
    announcement = get_object_or_404(scope.announcements().select_related("project", "created_by"), pk=pk)
    _mark_announcement_read(announcement, request.user)
    others = list(
        scope.announcements().exclude(pk=announcement.pk).annotate(is_read=scope.announcement_read())[:5]
    )
    return render(request, "portal/announcement_detail.html", {
        "announcement": announcement,
        "others": others,
        "crumbs": crumbs(("Announcements", reverse("portal:announcements")), (announcement.title, None)),
    })


@portal_api
def announcement_read(request, pk):
    scope = request.portal
    announcement = scope.announcements().filter(pk=pk).first()
    if announcement is None:
        return JsonResponse({"error": "not found"}, status=404)
    _mark_announcement_read(announcement, request.user)
    unread = scope.announcements().exclude(scope.announcement_read()).count()
    return JsonResponse({"ok": True, "unread": unread})


@require_POST
@portal_view
def announcements_read_all(request):
    scope = request.portal
    unread = list(scope.announcements().exclude(scope.announcement_read()).values_list("pk", flat=True))
    AnnouncementRead.objects.bulk_create(
        [AnnouncementRead(announcement_id=pk, user=request.user) for pk in unread], ignore_conflicts=True
    )
    if unread:
        messages.success(request, f"Marked {len(unread)} announcement{'s' if len(unread) != 1 else ''} as read.")
    return redirect("portal:announcements")


# ── Meetings ─────────────────────────────────────────────────────────────────

@portal_view
def meetings(request):
    user, now = request.user, timezone.now()
    upcoming = upcoming_meetings(user, now)
    upcoming_ids = {m.pk for m in upcoming}
    past_qs = (
        Meeting.objects.filter(invites__user=user, starts_at__lt=now)
        .exclude(pk__in=upcoming_ids)
        .select_related("project")
        .order_by("-starts_at")
    )
    page = paginate(request, past_qs, 10)
    for m in page.object_list:
        m.ends_at = m.starts_at + timezone.timedelta(minutes=m.duration_min or 0)
    return render(request, "portal/meetings.html", {
        "upcoming": upcoming,
        "page": page,
        "now": now,
        "page_title": "Meetings",
        "page_subtitle": "Calibration calls, trainings and team meetings you're invited to.",
        "crumbs": crumbs(("Meetings", None)),
    })


# ── Notifications ────────────────────────────────────────────────────────────

@portal_view
def notifications(request):
    qs = Notification.objects.filter(user=request.user).order_by("-created_at")
    show = request.GET.get("show")
    if show == "unread":
        qs = qs.filter(read_at__isnull=True)
    page = paginate(request, qs, 25)
    decorate_notifications(page.object_list)
    return render(request, "portal/notifications.html", {
        "page": page,
        "show": show,
        "page_title": "Notifications",
        "page_subtitle": "Everything that needs your attention, newest first.",
        "crumbs": crumbs(("Notifications", None)),
    })


@portal_view
def notifications_menu(request):
    """HTML fragment for the top-bar dropdown (loaded on demand by portal.js)."""
    items = decorate_notifications(list(Notification.objects.filter(user=request.user).order_by("-created_at")[:6]))
    return render(request, "portal/includes/notification_menu.html", {"items": items})


@portal_view
def notification_open(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    target = safe_internal_path(notification.link, request)
    return redirect(target or "portal:notifications")


@require_POST
@portal_view
def notifications_read_all(request):
    count = Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    if count:
        messages.success(request, f"Marked {count} notification{'s' if count != 1 else ''} as read.")
    nxt = safe_internal_path(request.POST.get("next", ""), request)
    return redirect(nxt or "portal:notifications")
