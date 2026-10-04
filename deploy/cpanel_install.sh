#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Skyloon AI — one-time installer for cPanel shared hosting.
#
# Run it in cPanel → Terminal, INSIDE the virtualenv that "Setup Python App" created:
#
#   source /home/<cpuser>/virtualenv/<app>/3.11/bin/activate && cd /home/<cpuser>/<app>
#   bash deploy/cpanel_install.sh
#
# It asks a few questions (domain, database, email), then installs the packages, writes .env,
# prepares the database and static files, creates your Super Admin login, loads the demo data
# (all sample content — SAMPLE_DATA=no skips it), adds the cron jobs and restarts the app.
# Safe to run again (it keeps an existing .env unless you say otherwise).
# Guide (Bangla): docs/DEPLOY_CPANEL_BN.md · full reference: docs/DEPLOY_CPANEL.md
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
ME="${USER:-$(id -un)}"

say()  { printf '\n\033[1;32m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
ask()  { local q="$1" def="${2:-}" a; read -r -p "$q${def:+ [$def]}: " a; echo "${a:-$def}"; }
asks() { local q="$1" a; read -r -s -p "$q: " a; echo >&2; echo "$a"; }

if [ -z "${VIRTUAL_ENV:-}" ]; then
  echo "Please activate the app's virtualenv first. cPanel → Setup Python App shows the command, e.g.:"
  echo "  source /home/$ME/virtualenv/$(basename "$APP_DIR")/3.11/bin/activate && cd $APP_DIR"
  exit 1
fi
PY="$VIRTUAL_ENV/bin/python"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python 3.10+ is required (choose it in Setup Python App)."; exit 1; }

say "1/7 Installing Python packages"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r requirements.txt

WRITE_ENV=yes
if [ -f .env ]; then
  [ "$(ask 'A .env file already exists. Keep it? (yes/no)' yes)" = "no" ] || WRITE_ENV=no
fi

if [ "$WRITE_ENV" = "yes" ]; then
  say "2/7 Settings (written to .env — outside public_html, never shared)"
  DOMAIN=$(ask "Your domain without https:// (e.g. skyloon.ai)")
  DOMAIN=${DOMAIN#https://}; DOMAIN=${DOMAIN#http://}; DOMAIN=${DOMAIN%/}; BARE=${DOMAIN#www.}
  echo "Database — create it first in cPanel → MySQL Databases (user added with ALL PRIVILEGES)."
  DB_NAME=$(ask "  Database name (e.g. ${ME}_skyloon)")
  DB_USER=$(ask "  Database user" "$DB_NAME")
  DB_PASSWORD=$(asks "  Database password")
  echo "Email — create a mailbox in cPanel → Email Accounts (e.g. no-reply@$BARE). Leave the host empty to set it later."
  EMAIL_HOST=$(ask "  SMTP host (e.g. mail.$BARE)" "mail.$BARE")
  EMAIL_USER=$(ask "  Mailbox / SMTP user" "no-reply@$BARE")
  EMAIL_PASSWORD=$(asks "  Mailbox password")
  ALERTS=$(ask "  Who receives quote / signup / application alerts" "hello@$BARE")
  SECRET=$("$PY" -c "import secrets; print(secrets.token_urlsafe(50))")
  mkdir -p "$HOME/skyloon_storage" "$HOME/logs"
  umask 077
  cat > .env <<ENV
DEBUG=false
SECRET_KEY=$SECRET
APP_URL=https://$DOMAIN
ALLOWED_HOSTS=$BARE,www.$BARE
CSRF_TRUSTED_ORIGINS=https://$BARE,https://www.$BARE
TIME_ZONE=Asia/Dhaka

DB_ENGINE=mysql
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=localhost
DB_PORT=3306

EMAIL_HOST=$EMAIL_HOST
EMAIL_PORT=465
EMAIL_USE_SSL=true
EMAIL_HOST_USER=$EMAIL_USER
EMAIL_HOST_PASSWORD=$EMAIL_PASSWORD
DEFAULT_FROM_EMAIL=Skyloon AI <$EMAIL_USER>
ADMIN_NOTIFICATION_EMAILS=$ALERTS
EMAIL_SEND_IMMEDIATELY=true

STORAGE_BACKEND=local
PRIVATE_STORAGE_DIR=$HOME/skyloon_storage
MEDIA_URL_TTL_SECONDS=10800

SECURE_HTTPS=true
SECURE_HSTS_SECONDS=0
BEHIND_HTTPS_PROXY=false
TRUSTED_PROXY_COUNT=0
LOG_FILE=$HOME/logs/skyloon.log
ENV
  umask 022
  chmod 600 .env
  echo "Saved .env (only your account can read it)."
else
  say "2/7 Keeping the existing .env"
fi

say "3/7 Checking the database connection"
"$PY" manage.py check --database default >/dev/null || { warn "Can't connect to the database — check DB_NAME / DB_USER / DB_PASSWORD in .env and that the user has ALL PRIVILEGES."; exit 1; }

say "4/7 Static files (CSS, JS, fonts)"
"$PY" manage.py collectstatic --noinput >/dev/null

say "5/7 Database tables"
"$PY" manage.py migrate --noinput
"$PY" manage.py createcachetable
"$PY" manage.py seed_demo --defaults >/dev/null

if [ "$("$PY" manage.py shell -c "from apps.accounts.models import User; print(User.objects.filter(is_superuser=True).exists())" | tail -1)" != "True" ]; then
  say "6/7 Your Super Admin login"
  if [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ]; then
    "$PY" manage.py createsuperuser --noinput   # uses DJANGO_SUPERUSER_EMAIL / _NAME / _PASSWORD
  else
    "$PY" manage.py createsuperuser
  fi
else
  say "6/7 A Super Admin already exists — skipped"
fi

# Demo data: the same complete sample set as the preview (3 projects, tutorials, tests with questions, feedback,
# work guide, practice tasks, announcements, meetings, sample employees and their progress), so every page has
# something to show from the first minute. Skip it with SAMPLE_DATA=no; remove it later with one command.
if [ "${SAMPLE_DATA:-yes}" != "no" ]; then
  say "Demo data (all sample content)"
  SAMPLE_PW="${SAMPLE_PASSWORD:-}"
  if [ -z "$SAMPLE_PW" ] && [ -t 0 ]; then
    SAMPLE_PW=$(asks "  Password for the demo accounts (press Enter and one is made for you)")
  fi
  if [ -n "$SAMPLE_PW" ] && [ "${#SAMPLE_PW}" -lt 8 ]; then
    warn "That password is shorter than 8 characters — making a strong one instead."; SAMPLE_PW=""
  fi
  "$PY" manage.py seed_demo --password "${SAMPLE_PW:-auto}"
  echo "  Remove all demo data later (before real employees join): python manage.py seed_demo --remove"
fi

say "7/7 Cron jobs and restart"
if command -v crontab >/dev/null 2>&1; then
  CRON_MAIL="*/5 * * * * $PY $APP_DIR/manage.py process_emails >/dev/null 2>&1"
  CRON_CLEAN="15 3 * * * $PY $APP_DIR/manage.py cleanup >/dev/null 2>&1"
  ( crontab -l 2>/dev/null | grep -v "$APP_DIR/manage.py process_emails" | grep -v "$APP_DIR/manage.py cleanup"; echo "$CRON_MAIL"; echo "$CRON_CLEAN" ) | crontab -
  echo "Cron jobs added (emails every 5 minutes, cleanup daily 03:15)."
else
  warn "crontab is not available here — add the two cron jobs in cPanel → Cron Jobs (see docs/DEPLOY_CPANEL_BN.md)."
fi
mkdir -p tmp && touch tmp/restart.txt

DOMAIN_SHOWN=$(grep '^APP_URL=' .env | cut -d= -f2-)
# Production check — HSTS (W004) and SSL redirect (W008) are handled by cPanel's "Force HTTPS".
ISSUES=$("$PY" manage.py check --deploy 2>&1 | grep -E "\((security|[a-z_]+)\.[EW][0-9]+\)" | grep -v "W004\|W008" || true)
[ -z "$ISSUES" ] || { warn "Please review:"; echo "$ISSUES"; }
printf '\n\033[1;32m✔ Done.\033[0m Open %s  ·  admin panel %s/admin/  ·  employees %s/login/\n' "$DOMAIN_SHOWN" "$DOMAIN_SHOWN" "$DOMAIN_SHOWN"
echo "Next: cPanel → Domains → turn on “Force HTTPS Redirect”, then Admin → Settings → company email, phone and address."
