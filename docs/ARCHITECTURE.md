# Skyloon AI — architecture & conventions

This document is the source of truth for how the codebase is organised. Read it
before adding features.

## 1. Platform constraints (cPanel shared hosting)

| Concern | Decision |
|---|---|
| Language / framework | Python 3.10+ · Django 5.2 LTS |
| Database | MySQL 8 / MariaDB 10.5+ via **PyMySQL** (pure Python — no compiler needed) |
| App server | Phusion Passenger through cPanel **Setup Python App** → `passenger_wsgi.py` |
| Static files | WhiteNoise (`collectstatic`), compiled Tailwind CSS is committed (`static/css/app.css`) — **no Node.js on the server** |
| Cache / rate limits | Django database cache (`createcachetable`) — no Redis |
| Background work | No workers. Emails go through an outbox (`EmailMessage`) and are delivered in-request; a cPanel cron runs `manage.py process_emails` for retries |
| Video | Never stored in the database. `STORAGE_BACKEND=s3` (Cloudflare R2 / Backblaze B2 / Wasabi / AWS S3 …): browsers upload with presigned PUT and stream with presigned GET. `local` mode streams from a private folder with signed, expiring, range-enabled URLs. External HLS/MP4 URLs (Bunny Stream, Cloudflare Stream) are also supported |
| Thumbnails | Generated in the browser (canvas frame capture) at upload time — no ffmpeg on the server |

## 2. Layout

```
config/            settings, urls, wsgi
passenger_wsgi.py  cPanel entry point
apps/
  core/            SiteSetting, Counter, AuditLog · markdown, rate limiting, template tags (ui), seed_demo
  accounts/        User (roles + status + employee ID), Organization, auth views, permissions, decorators
  storage/         MediaAsset · storage backends · upload/stream endpoints (/media/…)
  projects/        Project, Team, ProjectMember, Guideline, GuidelineAck · add_member()
  training/        TutorialCategory, Tutorial, TutorialProgress, OnboardingStep/Completion · progress tracking
  assessments/     Test, Question, QuestionOption, TestAssignment, TestAttempt · grading
  feedback/        Feedback (#001…), FeedbackRecipient
  comms/           Announcement, Meeting, Notification, EmailMessage · notify(), send_email()
  website/         Public site + QuoteRequest, ContactMessage, JobApplication
  portal/          Employee portal (views only)          → /portal/
  backoffice/      Admin panel (views only)             → /admin/
  clients/         Client portal placeholder (phase 2)  → /client/
templates/         base.html, layouts/, components/, emails/, errors/, accounts/, website/, portal/, backoffice/
static/            src/app.css (Tailwind source), css/app.css (compiled), js/, img/, fonts/, vendor/
```

## 3. Roles & permissions (`apps/accounts/permissions.py`)

Roles: `super_admin`, `project_manager`, `trainer` (Trainer/QA), `employee`, `client`.
Status: `pending` → `active` → `suspended`.

Check permission codes, never roles directly:

```python
from apps.accounts.decorators import permission_required_code, staff_required, employee_required
from apps.accounts.permissions import has_permission, project_scope, can_manage_project, can_manage_content_for

@permission_required_code("content.manage")
def tutorial_list(request):
    qs = project_scope(Tutorial.objects.all(), request.user)   # PM/Trainer only see their projects (+ company-wide)
```

In templates: `{% if perms_codes.employees_manage %}` is NOT available — compute flags in the view
(`can_edit = has_permission(request.user, "employees.manage")`) and pass them to the template.

## 4. Business logic lives in services — reuse them

| Need | Function |
|---|---|
| Approve / suspend / reactivate an account | `accounts.services.approve_user`, `suspend_user`, `reactivate_user` |
| Create an employee/staff account + invite email | `accounts.services.create_account(email=, name=, role=, invited_by=)` |
| Convert a job application into an employee | `accounts.services.convert_application(app, by)` → `Conversion(user, created, invited)`; raises `ConversionRefused` for suspended / non-employee accounts (existing accounts are linked, never changed) |
| Add someone to a project (assigns its content) | `projects.services.add_member(project, user, role=, team=)` |
| Qualify a member (onboarding step 8) | `projects.services.qualify_member(member, by_user)` |
| Publish a tutorial (assigns + notifies) | `training.services.publish_tutorial(tutorial)` |
| Assign a tutorial to specific users | `training.services.assign_tutorial(tutorial, users, due_at=)` |
| Record a video heartbeat | `training.services.record_tutorial_heartbeat(progress, duration=, ranges=, position=)` |
| Onboarding status for one user / a project | `training.services.onboarding_for_user(user)`, `onboarding_matrix(project, users)` |
| Complete a manual onboarding step | `training.services.complete_manual_step(step, user)` |
| Publish feedback (recipients + test + notify) | `feedback.services.publish_feedback(feedback)` |
| Feedback opened / video heartbeat | `feedback.services.mark_opened(recipient, has_video=)`, `record_feedback_heartbeat(...)` |
| Publish / assign a test | `assessments.services.publish_test(test)`, `assign_test(test, users, assigned_by=)` |
| A user's state on a test | `assessments.services.test_state(user, test)` → status `pending / in_progress / passed / review / locked` |
| Start / submit an attempt | `start_attempt(user, test)`, `attempt_questions(attempt)`, `submit_attempt(attempt, {qid: [oid…]})` |
| In-app notification (+ optional email) | `comms.services.notify(users, NotificationType.X, title, body, link, email_template=…, context=…)` |
| Email | `comms.services.send_email(to, subject, template, context)`, `notify_admins(subject, template, context)` |
| Absolute URL for emails | `comms.services.absolute_url(path)` |
| Company info (email, phone, address, socials) | `core.site_settings.company()`; in templates `{{ company.email }}` |
| Audit an admin action | `core.audit.log(request, "employee.approve", obj, **meta)` |
| Rate limit | `core.ratelimit.hit(key, limit, window_seconds)` → True when over the limit; `client_ip(request)` |
| Save an uploaded form file | `storage.services.store_uploaded_file(file, kind=MediaKind.DOCUMENT, purpose="cv")` |
| Signed URL to view/download an asset | `storage.services.media_url(asset, request.user, download=False)` — only after checking access to the parent object |

Video watch tracking: the player posts `{duration, position, ranges}` where `ranges` come from
`HTMLMediaElement.played`. The server merges ranges and caps new coverage by wall-clock time
(`training/progress.py`), so a video is only "watched" when ≥ `VIDEO_COMPLETION_THRESHOLD`% has
really been played.

## 5. Media upload API (admin panel)

All endpoints require `content.manage` or `projects.manage` and a CSRF header (`X-CSRFToken`).

1. `POST /media/uploads/init/` `{filename, size, mime_type, kind: video|image|document, purpose}` →
   `{id, mode: "put", url, headers}` (S3: PUT the file to `url`) **or**
   `{id, mode: "chunked", url, chunk_size}` (local: POST raw chunks to `url` with header `X-Chunk-Offset`).
2. `POST /media/uploads/<id>/complete/` `{duration, width, height, thumbnail_id}` → asset JSON (`id, url, thumbnail_url, …`).
3. `POST /media/external/` `{url, duration?}` registers an external `.m3u8`/`.mp4` URL.
4. `GET /media/<id>/info/` asset JSON · `GET /media/<id>/preview/` redirects to a fresh signed URL.

Thumbnails: upload a JPEG captured from a `<canvas>` as `kind=image, purpose=thumbnail` first, then pass its id to `complete`.

## 6. Front-end conventions

* Templates extend `base.html` (public), `layouts/app_shell.html` (portal/admin) or `layouts/auth.html`.
* The design system lives in `static/src/app.css`. Prefer its component classes:
  `container-page section eyebrow heading-xl heading-lg heading-md lead dark-surface grid-bg text-gradient reveal`
  `btn btn-primary btn-accent btn-secondary btn-ghost btn-danger btn-danger-soft btn-success btn-light btn-white btn-sm btn-lg btn-icon`
  `label input select textarea checkbox file-input help-text field-error choice-list choice-pill`
  `card card-header card-title card-body card-dark divider badge badge-{success,warning,danger,info,brand,neutral} dot`
  `table-wrap table num progress progress-bar tabs tab is-active side-link side-heading page-title page-subtitle`
  `alert alert-{success,error,warning,info} stat stat-label stat-value stat-meta prose-content`
  Colours: `ink-950…600` (navy), `brand-50…900` (indigo), `accent-300…500` (cyan), `label-{lime,amber,pink,violet,cyan}`.
* Components (`templates/components/`): `field.html`, `form_errors.html`, `honeypot.html`, `messages.html`,
  `pagination.html`, `empty_state.html`, `progress.html`, `avatar.html`, `page_header.html`, `logo.html`.
* Template helpers (builtin, no `{% load %}` needed): `{% icon "name" class="h-4 w-4" %}` (Lucide subset — see
  `apps/core/icons.py`), `{% brand_icon "linkedin" %}`, `{{ text|markdown }}`, `{{ secs|duration }}`, `{{ v|percent }}`,
  `{{ bytes|filesize_h }}`, `{% status_badge value label %}`, `{% nav_active "/portal/training" %}`, `{{ name|initials }}`,
  `{{ dict|get_item:key }}`, `{{ "a,b"|split }}`, Django's `{% querystring page=2 %}`.
* Forms: subclass `StyledFormMixin` (adds CSS classes) and render fields with `components/field.html`.
* JS: vanilla, no build step. `static/js/site.js` is loaded everywhere and exposes
  `window.skyleon.postJSON(url, data)` / `window.skyleon.csrfToken()`. Page-specific scripts go in `{% block scripts %}`.
  Data attributes: `data-confirm="…"` on forms, `data-autosubmit` on filter forms, `data-toggle="#id"`, `data-copy`.
* CSS is compiled by Tailwind from the templates. A watcher rebuilds `static/css/app.css` in development; otherwise run `npm run build:css`.

## 7. Testing

* `python manage.py check`
* `python manage.py test apps.<app>` (MySQL test DB; set `DB_TEST_NAME` to use a different test database name)
* Demo data: `python manage.py seed_demo` — accounts `admin@`, `pm@`, `trainer@`, `employee1..8@skyleon.local`,
  `client@northwind.example`, password `Demo@12345`.
