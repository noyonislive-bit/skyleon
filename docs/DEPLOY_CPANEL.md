# Deploying on cPanel shared hosting

The application is a standard Django (WSGI) app. cPanel runs it with Phusion Passenger
through **Setup Python App**. No Node.js, Redis, Docker or root access is needed.

**Requirements:** cPanel with *Setup Python App* (CloudLinux Python Selector), Python **3.10 or newer**
(3.11/3.12 recommended), MySQL 8 or MariaDB 10.5+, SSH or *Terminal* access (recommended), an SSL
certificate (AutoSSL is fine).

> **Quick way:** after steps 1–3 below, run `bash deploy/cpanel_install.sh` in the app's virtualenv (cPanel → Terminal).
> It asks for the domain, database and email details and does steps 4, 5 and 7 for you. Updates: `bash deploy/cpanel_update.sh`.
> Step-by-step guide in Bangla: [`DEPLOY_CPANEL_BN.md`](DEPLOY_CPANEL_BN.md).

---

## 1. Create the database

cPanel → **MySQL® Databases**

1. Create a database, e.g. `cpuser_skyloon`.
2. Create a user, e.g. `cpuser_skyloon`, with a strong password.
3. Add the user to the database with **ALL PRIVILEGES**.

The app connects with `utf8mb4` automatically. If your host lets you choose, set the database
collation to `utf8mb4_unicode_ci`.

## 2. Upload the code

Put the project **outside `public_html`**, e.g. `/home/cpuser/skyloon`.

* **Git:** cPanel → *Git™ Version Control* → *Create* → clone the repository into `/home/cpuser/skyloon`; or
* **Upload:** zip the project (without `.venv`, `node_modules`, `storage`, `staticfiles`) and extract it with *File Manager*.

## 3. Create the Python application

cPanel → **Setup Python App** → *Create Application*

| Field | Value |
|---|---|
| Python version | 3.11 (or newest available ≥ 3.10) |
| Application root | `skyloon` (the folder from step 2) |
| Application URL | your domain (e.g. `example.com`) |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

Click **Create**. cPanel creates a virtualenv and shows a command such as:

```bash
source /home/cpuser/virtualenv/skyloon/3.11/bin/activate && cd /home/cpuser/skyloon
```

## 4. Install dependencies and configure

Open **Terminal** (or SSH), run the command shown above, then:

```bash
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
nano .env          # fill in SECRET_KEY, APP_URL, ALLOWED_HOSTS, DB_*, EMAIL_*, storage
```

Generate a secret key with `python -c "import secrets; print(secrets.token_urlsafe(50))"`.

> No terminal? In *Setup Python App* use **Run Pip Install** with `requirements.txt`, and add the
> environment variables in the *Environment variables* section instead of a `.env` file.

## 5. Initialise the database and static files

```bash
python manage.py collectstatic --noinput    # first: pages need the static-files manifest
python manage.py migrate
python manage.py createcachetable
python manage.py seed_demo --defaults        # tutorial categories
python manage.py createsuperuser             # your Super Admin login (email + name + password)
```

Restart the app: *Setup Python App* → **Restart** (or `touch tmp/restart.txt`).

Open `https://your-domain/` (public site), `https://your-domain/login/` (staff & employees) and
`https://your-domain/admin/` (admin panel). Then go to **Admin → Settings** and enter the company
email, phone, address, business hours and social links shown on the website.

> **Demo data.** The installer loads the complete sample set (3 projects, tutorials, tests with questions,
> feedback, a work guide, Practice Lab tasks, announcements, meetings, enquiries and sample employees with
> their progress) so every page has something to show. Demo account passwords are generated, printed and saved
> in `SAMPLE_LOGINS.txt` next to `manage.py` (mode 600, not web-accessible); no extra super admin is created.
> `cpanel_update.sh` tops it up (`seed_demo --if-outdated --password auto`). Load or remove it in the browser:
> Admin → Settings → *Demo data*, or `python manage.py seed_demo --remove` (keeps your own data; not re-added).
> Install without it: `SAMPLE_DATA=no bash deploy/cpanel_install.sh`.

## 6. Force HTTPS

cPanel → *Domains* → enable **Force HTTPS Redirect**, or add at the top of
`public_html/.htaccess` (above the Passenger lines cPanel generated):

```apache
RewriteEngine On
RewriteCond %{HTTPS} !=on
RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]
```

Keep `SECURE_HTTPS=true` in `.env`. Once everything works over HTTPS you can set
`SECURE_HSTS_SECONDS=31536000`.

## 7. Cron jobs

cPanel → **Cron Jobs** (replace the paths with the ones from step 3):

| Schedule | Command |
|---|---|
| Every 5 minutes | `/home/cpuser/virtualenv/skyloon/3.11/bin/python /home/cpuser/skyloon/manage.py process_emails >/dev/null 2>&1` |
| Daily 03:15 | `/home/cpuser/virtualenv/skyloon/3.11/bin/python /home/cpuser/skyloon/manage.py cleanup >/dev/null 2>&1` |

`process_emails` retries any email that could not be sent immediately (e.g. SMTP hiccup).
`cleanup` removes expired sessions, abandoned uploads and old delivered / failed emails.
To honour the privacy policy, you can also let it delete personal data that is no longer needed:
`manage.py cleanup --purge-days 365` removes rejected job applications and closed quote requests /
messages older than 365 days (with their uploaded files).

## 8. Email

Create a mailbox such as `no-reply@your-domain` (cPanel → *Email Accounts*). *Connect Devices*
shows the SMTP host/port. Put them in `.env` (`EMAIL_HOST`, `EMAIL_PORT=465`, `EMAIL_USE_SSL=true`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`). Add SPF/DKIM (cPanel →
*Email Deliverability*) so messages don't land in spam.

## 9. Video storage (important)

Training and feedback videos should **not** live on the shared-hosting disk once volume grows.
Use S3-compatible object storage — videos are uploaded from the browser **directly** to the bucket
and streamed from it with short-lived signed URLs, so your hosting bandwidth and CPU are not used:

* **Cloudflare R2** (no egress fees — recommended), **Backblaze B2**, **Wasabi**, **AWS S3**, **Bunny Storage**.

`.env`:

```ini
STORAGE_BACKEND=s3
S3_BUCKET=skyloon-media
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
```

Keep the bucket **private** and add a CORS rule so browsers can upload/stream from your domain:

```json
[
  {
    "AllowedOrigins": ["https://your-domain"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["Content-Type", "Range"],
    "ExposeHeaders": ["ETag", "Content-Length", "Content-Range"],
    "MaxAgeSeconds": 3600
  }
]
```

Upload limits: a single upload can be up to 5 GB with S3. In `local` mode uploads are sent in 5 MB
chunks, which works within typical shared-hosting request limits; files are stored in
`PRIVATE_STORAGE_DIR` (outside `public_html`) and streamed through signed, expiring URLs.

You can also paste an **external HLS (`.m3u8`) or MP4 URL** from a streaming service such as
Bunny Stream or Cloudflare Stream when creating a tutorial or feedback item; playback is still
tracked by the portal.

## 10. Updating

```bash
source /home/cpuser/virtualenv/skyloon/3.11/bin/activate && cd /home/cpuser/skyloon
git pull                       # or upload the new files
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
touch tmp/restart.txt
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Incomplete response" / 500 right after deploy | Check `stderr.log` in the app root; usually a missing `.env` value (`SECRET_KEY`, `ALLOWED_HOSTS`) or DB credentials |
| Every page returns 500 after an update ("Missing staticfiles manifest entry" in the log) | Run `collectstatic --noinput`, then restart the app — templates refer to the hashed file names in that manifest |
| `CSRF verification failed` on forms | `CSRF_TRUSTED_ORIGINS` must contain `https://your-domain` (and `www.` variant) |
| Emails not arriving | Check *Admin → Email log*; verify SMTP values; run `python manage.py process_emails` |
| `Access denied for user` | The DB user is not added to the database with ALL PRIVILEGES |
| Videos don't play from S3 | Check the bucket CORS rule and that `S3_ENDPOINT_URL` is correct |
| Changes not visible | Restart the app (`touch tmp/restart.txt`) |

## Security notes

* **Rate limits** (login, signup, password reset, public forms) use the visitor's IP address. On plain cPanel
  hosting leave `TRUSTED_PROXY_COUNT=0` and `BEHIND_HTTPS_PROXY=false`. Only when the site is behind
  Cloudflare or another proxy set `TRUSTED_PROXY_COUNT=1` and `BEHIND_HTTPS_PROXY=true`.
* `/django-admin/` (low-level database admin, super admins only) signs in through the normal, rate-limited login page.
* Uploaded files are never shown as web pages: anything other than video, audio, images, PDF and plain text is
  always downloaded, and every file is served with a sandboxing Content-Security-Policy.
* Request bodies larger than `MAX_REQUEST_BODY_MB` (default 30 MB) are refused before they are read; videos use
  chunked uploads. If your host's ModSecurity limits request bodies, keep `UPLOAD_CHUNK_SIZE` below that limit.
* Password-reset emails go through the email outbox too, so they appear in **Admin → Email log** and are retried.
