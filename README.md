# Skyloon AI — AI Data Annotation website & employee training portal

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/noyonislive-bit/skyleon/tree/claude/eager-cori-wcmlyv)

One web application with three areas:

| Area | URL | Who |
|---|---|---|
| **Public website**: services, industries, solutions, quality, platforms, about, careers, contact, request a quote | `/` | Prospective clients & applicants |
| **Employee portal**: onboarding, tutorials, daily feedback, tests, results, announcements | `/portal/` | Employees (and staff) |
| **Admin panel**: employees, applicants, leads, projects, training, feedback tracking, tests, reports, settings | `/admin/` | Super Admin · Project Manager · Trainer/QA |
| Client portal (phase-2 groundwork) | `/client/` | Client users |

Built with **Python (Django 5.2 LTS) + MySQL/MariaDB** and designed to run on **cPanel shared hosting**
(Passenger "Setup Python App"). The server needs no Node.js, Redis, Docker or background workers.

- **Deployment guide:** [`docs/DEPLOY_CPANEL.md`](docs/DEPLOY_CPANEL.md)
- **Architecture & conventions:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## Highlights

**Public website**
- Premium AI/enterprise design with inline SVG annotation visuals (no stock photos), responsive, fast (self-hosted fonts, no CDNs).
- Request-a-quote, contact and careers forms: saved to the database, email alerts to admins, confirmation emails, file uploads (CV/samples), spam honeypot and rate limiting.
- SEO: clean URLs, per-page meta and Open Graph tags, `sitemap.xml`, `robots.txt`, JSON-LD schema, SEO landing pages.

**Employee portal**
- Sign up → manager approval → employee ID (e.g. `SKY-0042`) → project assignment → onboarding → training → feedback → tests.
- **Tracked video playback.** Progress is recorded from the parts of a video the employee actually played. It resumes where they stopped, and completion is never a button click. Required videos can't be skipped ahead.
- Daily/weekly QA feedback (`#001 · Hand visibility`) with video, explanation, acknowledgement and a follow-up test.
- Tests with multiple-choice, multi-select, true/false, image/video questions and image options ("select the correct segmentation"). Scoring is automatic, with passing score, attempt limits, time limits and result history.
- 8-step onboarding per project, with steps that complete themselves (tutorial watched, test passed, manager qualification).

**Admin panel**
- Analytics dashboard: employees, approvals, applicants, training completion, unseen feedback, pending tests, average score, team size per project.
- Employees (approve, suspend, edit, roles, assign project/training/feedback/tests, progress), applicants, quote requests and messages.
- Projects with teams, guidelines, onboarding steps and members. Tutorials with direct video upload (browser-generated thumbnails).
- **Feedback tracking**: who watched each feedback item, test result, score and status, with filters and CSV export.
- Test builder, results, training-progress matrix, employee reports, announcements, meetings (manual Meet/Zoom links), email log, company settings.

**Security**
- Role-based access: Super Admin, Project Manager, Trainer/QA, Employee, Client. Project managers and trainers are limited to their own projects.
- Django password hashing (PBKDF2), session security, CSRF protection, login rate limiting, protection against open redirects.
- Private files live outside `public_html` or in a private bucket. They are served through short-lived signed URLs; local-storage URLs only work for the logged-in user they were issued to.

---

## Preview from GitHub (Codespaces — nothing to install)

1. Click the **Open in GitHub Codespaces** button above (or on GitHub: **Code → Codespaces → Create codespace on
   `claude/eager-cori-wcmlyv`**).
2. Wait 2–3 minutes while it installs everything and loads the demo data.
3. The website opens automatically on port 8000 (otherwise: **Ports** tab → 8000 → *Open in Browser*).

The preview link is private to your GitHub account. Demo logins are listed below and in `.devcontainer/PREVIEW.md`.
Codespaces is free for personal accounts up to a monthly quota; stop the codespace when you are done
(github.com/codespaces → … → Stop).

## Try it on your computer (5 minutes, no MySQL needed)

Needs **Python 3.10+** (python.org, tick "Add python.exe to PATH" on Windows) and **Git** (or download the ZIP of the branch from GitHub).

```bash
git clone -b claude/eager-cori-wcmlyv https://github.com/noyonislive-bit/skyleon.git
cd skyleon
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

Create a file named `.env` in the `skyleon` folder with:

```ini
DEBUG=true
SECRET_KEY=local-test-key
DB_ENGINE=sqlite
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

Then:

```bash
python manage.py migrate
python manage.py createcachetable
python manage.py seed_demo
python manage.py runserver
```

Open http://127.0.0.1:8000 in Chrome / Edge. Log in at http://127.0.0.1:8000/login/ with the demo accounts below
(password `Demo@12345`). Emails are printed in the terminal instead of being sent. SQLite mode is for testing only —
the live site uses MySQL (see the deployment guide).

## Local development

Requirements: Python 3.10+, MySQL 8 / MariaDB 10.5+ (Node.js only if you change templates/CSS).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# database
mysql -uroot -e "CREATE DATABASE skyleon CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                 CREATE USER 'skyleon'@'localhost' IDENTIFIED BY 'skyleon';
                 GRANT ALL ON skyleon.* TO 'skyleon'@'localhost';
                 GRANT ALL ON \`test\_skyleon%\`.* TO 'skyleon'@'localhost';"

cp .env.example .env     # set DEBUG=true, SECRET_KEY, DB_* (and EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend)
python manage.py migrate
python manage.py createcachetable
python manage.py seed_demo          # demo data, accounts below
python manage.py runserver
```

Demo accounts (password `Demo@12345`):

| Role | Login |
|---|---|
| Super Admin | `admin@skyleon.local` |
| Project Manager | `pm@skyleon.local` |
| Trainer / QA | `trainer@skyleon.local` |
| Employees | `employee1@skyleon.local` … `employee8@skyleon.local` (or their employee ID, e.g. `SKY-0004`) |
| Pending signups | `new.member1@skyleon.local`, `new.member2@skyleon.local` |
| Client | `client@northwind.example` |

### CSS

Styles are Tailwind CSS v4, compiled to `static/css/app.css`, which is committed, so the server never builds CSS.
After changing templates:

```bash
npm install
npm run build:css      # or: npm run watch:css
```

### Tests

```bash
python manage.py test apps          # unit + integration tests (MySQL test database)
python manage.py check --deploy     # production settings check (with DEBUG=false)
```

---

## Configuration

All settings come from environment variables / `.env` (see [`.env.example`](.env.example)):
database, email (SMTP from cPanel), storage (`local` or S3-compatible), HTTPS, video completion threshold,
employee ID prefix. Company details shown on the website (email, phone, address, hours, social links)
are edited in **Admin → Settings**.

## Video architecture

Videos are never stored in the database or `public_html`.

- **Recommended for production:** S3-compatible object storage (Cloudflare R2, Backblaze B2, Wasabi, AWS S3). The browser uploads directly to the bucket with a presigned URL and streams from it with expiring signed URLs, so shared-hosting bandwidth/CPU is not used.
- **Starter mode (`STORAGE_BACKEND=local`):** files are stored in a private folder, uploaded in 5 MB chunks, and streamed with HTTP Range support through signed, expiring, per-user URLs.
- **External streaming:** paste an HLS (`.m3u8`) or MP4 URL from Bunny Stream / Cloudflare Stream. Playback tracking still works (hls.js is loaded only when needed).

## Extending (phase 2+)

The data model already contains `Organization` and the `client` role, with projects linked to client
organisations (`/client/` shows a first read-only view). Each feature area is its own Django app with a
service layer, so new modules can be added without reworking existing ones:
client dashboards, production/QA statistics, certificates, attendance, payments, task assignment,
Slack/Google Meet integrations, CRM or a REST API.
