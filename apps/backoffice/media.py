"""
Which stored files (MediaAsset) a staff member may see or attach.

A MediaAsset has no owner field of its own — access follows the object it is
attached to:

  * training content (tutorial / feedback videos, question and option media,
    practice-task videos, work-guide videos, guideline documents — and the thumbnails of those
    videos) → the content's project must be in the viewer's scope
    (company-wide content, project NULL, is visible to all content staff);
  * job-application CVs / work samples → `applicants.manage`;
  * quote-request attachments → `leads.manage`;
  * a file the staff member uploaded themselves (not attached yet) → allowed.

Super admins may see everything. Everything else is treated as not found.
"""

from django.apps import apps
from django.db.models import Q

from apps.accounts.permissions import has_permission, is_unscoped
from apps.storage.models import MediaAsset

from .helpers import scope_ids


def _scoped(qs, field, project_ids, *, nullable=True):
    if project_ids is None:
        return qs
    cond = Q(**{f"{field}__in": project_ids})
    if nullable:
        cond |= Q(**{f"{field}__isnull": True})
    return qs.filter(cond)


def _content_asset_subqueries(project_ids):
    """Subqueries of asset ids attached to training content inside the given project scope."""
    from apps.assessments.models import Question, QuestionOption
    from apps.feedback.models import Feedback
    from apps.projects.models import Guideline
    from apps.training.models import Tutorial

    subs = [
        _scoped(Tutorial.objects.filter(video__isnull=False), "project", project_ids).values("video_id"),
        _scoped(Feedback.objects.filter(video__isnull=False), "project", project_ids).values("video_id"),
        _scoped(Question.objects.filter(media__isnull=False), "test__project", project_ids).values("media_id"),
        _scoped(QuestionOption.objects.filter(media__isnull=False), "question__test__project", project_ids).values("media_id"),
        _scoped(Guideline.objects.filter(document__isnull=False), "project", project_ids, nullable=False).values("document_id"),
    ]
    if apps.is_installed("apps.guides"):
        from apps.guides.models import GuideStep, GuideTaskError

        subs.append(_scoped(GuideStep.objects.filter(video_asset__isnull=False), "guide__project", project_ids).values("video_asset_id"))
        subs.append(_scoped(GuideTaskError.objects.filter(video_asset__isnull=False), "guide__project", project_ids).values("video_asset_id"))
    if apps.is_installed("apps.practice"):
        from apps.practice.models import PracticeTask

        subs.append(_scoped(PracticeTask.objects.filter(video__isnull=False), "project", project_ids).values("video_id"))
    return subs


def content_assets_q(user, *, include_own=True) -> Q:
    """Q() over MediaAsset: files attached to content in the user's scope (+ their thumbnails, + own uploads)."""
    cond = Q(pk__in=[])
    for sub in _content_asset_subqueries(scope_ids(user)):
        cond |= Q(pk__in=sub) | Q(thumbnail_of__pk__in=sub)
    if include_own:
        cond |= Q(uploaded_by=user)
    return cond


def content_assets(user, qs=None):
    qs = MediaAsset.objects.all() if qs is None else qs
    return qs.filter(content_assets_q(user))


def can_attach_asset(user, asset) -> bool:
    """May `user` attach `asset` to a piece of content (form fields holding an asset id)?"""
    if user is None or asset is None or not getattr(user, "is_authenticated", False):
        return False
    if asset.uploaded_by_id == user.pk:
        return True
    return content_assets(user, MediaAsset.objects.filter(pk=asset.pk)).exists()


def _private_parent(asset):
    """'applicant' / 'lead' when the file belongs to a job application or a quote request."""
    from apps.website.models import JobApplication, QuoteRequest

    if JobApplication.objects.filter(Q(cv=asset) | Q(sample=asset)).exists():
        return "applicant"
    if QuoteRequest.objects.filter(attachment=asset).exists():
        return "lead"
    return None


def can_view_asset(user, asset) -> bool:
    """May a staff member get a signed URL for `asset` (admin-panel preview / download)?"""
    if asset is None or not has_permission(user, "backoffice.access"):
        return False
    if is_unscoped(user):
        return True
    parent = _private_parent(asset)
    if parent == "applicant":
        return has_permission(user, "applicants.manage")
    if parent == "lead":
        return has_permission(user, "leads.manage")
    if not (has_permission(user, "content.manage") or has_permission(user, "projects.manage")):
        return False
    return can_attach_asset(user, asset)
