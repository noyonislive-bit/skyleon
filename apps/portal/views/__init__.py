"""Employee portal views, grouped by area. All views are wrapped with scope.portal_view / portal_api."""

from .account import history, profile
from .assessments import (
    result_detail,
    results,
    test_detail,
    test_list,
    test_start,
    test_take,
)
from .comms import (
    announcement_detail,
    announcement_read,
    announcements,
    announcements_read_all,
    meetings,
    notification_open,
    notifications,
    notifications_menu,
    notifications_read_all,
)
from .dashboard import dashboard
from .feedback import feedback_ack, feedback_detail, feedback_heartbeat, feedback_list
from .onboarding import complete_step, onboarding
from .projects import guideline_ack, guideline_detail, project_detail, project_list
from .training import training, tutorial_complete, tutorial_detail, tutorial_heartbeat

__all__ = [
    "announcement_detail", "announcement_read", "announcements", "announcements_read_all", "complete_step",
    "dashboard", "feedback_ack", "feedback_detail", "feedback_heartbeat", "feedback_list", "guideline_ack",
    "guideline_detail", "history", "meetings", "notification_open", "notifications", "notifications_menu",
    "notifications_read_all", "onboarding", "profile", "project_detail", "project_list", "result_detail", "results",
    "test_detail", "test_list", "test_start", "test_take", "training", "tutorial_complete", "tutorial_detail", "tutorial_heartbeat",
]
