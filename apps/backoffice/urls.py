"""
Admin panel routes (/admin/…).

Contract — these names are used by emails and the public website and must stay:
dashboard, employee_detail, applicant_detail, lead_detail, message_detail.
"""

from django.urls import path

from .views import applicants, assessments, comms, dashboard, employees, feedback, insights, leads, projects, system, tutorials

app_name = "backoffice"

urlpatterns = [
    path("", dashboard.dashboard, name="dashboard"),

    # People
    path("employees/", employees.employee_list, name="employee_list"),
    path("employees/new/", employees.employee_create, name="employee_create"),
    path("employees/<int:pk>/", employees.employee_detail, name="employee_detail"),
    path("employees/<int:pk>/edit/", employees.employee_edit, name="employee_edit"),
    path("employees/<int:pk>/status/", employees.employee_status, name="employee_status"),
    path("employees/<int:pk>/role/", employees.employee_role, name="employee_role"),
    path("employees/<int:pk>/password-link/", employees.employee_invite, name="employee_invite"),
    path("employees/<int:pk>/projects/", employees.employee_add_project, name="employee_add_project"),
    path("employees/<int:pk>/assign/tutorial/", employees.employee_assign_tutorial, name="employee_assign_tutorial"),
    path("employees/<int:pk>/assign/feedback/", employees.employee_assign_feedback, name="employee_assign_feedback"),
    path("employees/<int:pk>/assign/test/", employees.employee_assign_test, name="employee_assign_test"),
    path("members/<int:pk>/update/", employees.member_update, name="member_update"),
    path("members/<int:pk>/remove/", employees.member_remove, name="member_remove"),
    path("members/<int:pk>/qualify/", employees.member_qualify, name="member_qualify"),

    path("applicants/", applicants.applicant_list, name="applicant_list"),
    path("applicants/<int:pk>/", applicants.applicant_detail, name="applicant_detail"),
    path("applicants/<int:pk>/convert/", applicants.applicant_convert, name="applicant_convert"),

    # Business
    path("leads/", leads.lead_list, name="lead_list"),
    path("leads/<int:pk>/", leads.lead_detail, name="lead_detail"),
    path("messages/", leads.message_list, name="message_list"),
    path("messages/<int:pk>/", leads.message_detail, name="message_detail"),

    # Projects
    path("projects/", projects.project_list, name="project_list"),
    path("projects/new/", projects.project_create, name="project_create"),
    path("projects/<int:pk>/", projects.project_detail, name="project_detail"),
    path("projects/<int:pk>/edit/", projects.project_edit, name="project_edit"),
    path("projects/<int:pk>/members/", projects.project_members, name="project_members"),
    path("projects/<int:pk>/teams/", projects.project_teams, name="project_teams"),
    path("projects/<int:pk>/guidelines/", projects.project_guidelines, name="project_guidelines"),
    path("projects/<int:pk>/guidelines/new/", projects.guideline_create, name="guideline_create"),
    path("projects/<int:pk>/onboarding/", projects.project_onboarding, name="project_onboarding"),
    path("projects/<int:pk>/onboarding/new/", projects.step_create, name="step_create"),
    path("projects/<int:pk>/onboarding/template/", projects.onboarding_template, name="onboarding_template"),
    path("projects/<int:pk>/content/", projects.project_content, name="project_content"),
    path("teams/<int:pk>/update/", projects.team_update, name="team_update"),
    path("teams/<int:pk>/delete/", projects.team_delete, name="team_delete"),
    path("guidelines/<int:pk>/edit/", projects.guideline_edit, name="guideline_edit"),
    path("guidelines/<int:pk>/delete/", projects.guideline_delete, name="guideline_delete"),
    path("onboarding/<int:pk>/edit/", projects.step_edit, name="step_edit"),
    path("onboarding/<int:pk>/delete/", projects.step_delete, name="step_delete"),
    path("onboarding/<int:pk>/move/", projects.step_move, name="step_move"),

    # Training
    path("tutorials/", tutorials.tutorial_list, name="tutorial_list"),
    path("tutorials/new/", tutorials.tutorial_create, name="tutorial_create"),
    path("tutorials/categories/", tutorials.category_list, name="category_list"),
    path("tutorials/categories/<int:pk>/edit/", tutorials.category_edit, name="category_edit"),
    path("tutorials/categories/<int:pk>/delete/", tutorials.category_delete, name="category_delete"),
    path("tutorials/<int:pk>/", tutorials.tutorial_detail, name="tutorial_detail"),
    path("tutorials/<int:pk>/edit/", tutorials.tutorial_edit, name="tutorial_edit"),
    path("tutorials/<int:pk>/status/", tutorials.tutorial_status, name="tutorial_status"),
    path("tutorials/<int:pk>/assign/", tutorials.tutorial_assign, name="tutorial_assign"),
    path("tutorials/<int:pk>/delete/", tutorials.tutorial_delete, name="tutorial_delete"),
    path("training/", insights.training_progress, name="training_progress"),

    # Quality
    path("feedback/", feedback.feedback_list, name="feedback_list"),
    path("feedback/new/", feedback.feedback_create, name="feedback_create"),
    path("feedback/tracking/", feedback.feedback_tracking, name="feedback_tracking"),
    path("feedback/<int:pk>/", feedback.feedback_detail, name="feedback_detail"),
    path("feedback/<int:pk>/edit/", feedback.feedback_edit, name="feedback_edit"),
    path("feedback/<int:pk>/publish/", feedback.feedback_publish, name="feedback_publish"),
    path("feedback/<int:pk>/status/", feedback.feedback_status, name="feedback_status"),
    path("feedback/<int:pk>/recipients/", feedback.feedback_recipients, name="feedback_recipients"),
    path("feedback/<int:pk>/test/new/", feedback.feedback_test_create, name="feedback_test_create"),
    path("feedback/<int:pk>/test/link/", feedback.feedback_test_link, name="feedback_test_link"),

    path("tests/", assessments.test_list, name="test_list"),
    path("tests/new/", assessments.test_create, name="test_create"),
    path("tests/<int:pk>/", assessments.test_builder, name="test_builder"),
    path("tests/<int:pk>/edit/", assessments.test_edit, name="test_edit"),
    path("tests/<int:pk>/questions/new/", assessments.question_create, name="question_create"),
    path("tests/<int:pk>/publish/", assessments.test_publish, name="test_publish"),
    path("tests/<int:pk>/status/", assessments.test_status, name="test_status"),
    path("tests/<int:pk>/assign/", assessments.test_assign, name="test_assign"),
    path("tests/<int:pk>/results/", assessments.test_results, name="test_results"),
    path("questions/<int:pk>/edit/", assessments.question_edit, name="question_edit"),
    path("questions/<int:pk>/delete/", assessments.question_delete, name="question_delete"),
    path("questions/<int:pk>/move/", assessments.question_move, name="question_move"),
    path("attempts/<int:pk>/", assessments.attempt_detail, name="attempt_detail"),

    # Communication
    path("announcements/", comms.announcement_list, name="announcement_list"),
    path("announcements/new/", comms.announcement_create, name="announcement_create"),
    path("announcements/<int:pk>/edit/", comms.announcement_edit, name="announcement_edit"),
    path("announcements/<int:pk>/delete/", comms.announcement_delete, name="announcement_delete"),
    path("meetings/", comms.meeting_list, name="meeting_list"),
    path("meetings/new/", comms.meeting_create, name="meeting_create"),
    path("meetings/<int:pk>/", comms.meeting_detail, name="meeting_detail"),
    path("meetings/<int:pk>/edit/", comms.meeting_edit, name="meeting_edit"),
    path("meetings/<int:pk>/cancel/", comms.meeting_cancel, name="meeting_cancel"),
    path("emails/", comms.email_list, name="email_list"),
    path("emails/retry/", comms.email_retry, name="email_retry"),
    path("emails/<int:pk>/", comms.email_detail, name="email_detail"),

    # Insights / system
    path("reports/", insights.reports, name="reports"),
    path("settings/", system.settings_view, name="settings"),
    path("audit/", system.audit_log, name="audit_log"),
]
