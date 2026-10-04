#!/bin/bash
# Claude Code cloud sessions: get the local preview of the site running whenever the session's
# container starts (it is recycled after inactivity, which stops the database and the dev server).
#   1. Python virtualenv + requirements      3. .env for local development
#   2. MariaDB (database + user)              4. migrate (+ demo data on an empty database)
#   5. Django dev server on http://127.0.0.1:8000 (background, log: /tmp/skyleon-runserver.log)
# Idempotent and non-interactive; does nothing outside cloud sessions.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
log() { echo "[session-start] $*" >&2; }

# 1. Python ------------------------------------------------------------------
if [ ! -x .venv/bin/python ]; then
  log "creating virtualenv"
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
PY=.venv/bin/python

# 2. Database ----------------------------------------------------------------
DB_ENGINE=mysql
if ! command -v mariadb >/dev/null 2>&1 && ! command -v mysqld >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    log "installing mariadb-server"
    (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mariadb-server >/dev/null) || DB_ENGINE=sqlite
  else
    DB_ENGINE=sqlite
  fi
fi

# 3. .env (local development only — never used in production) ------------------
if [ ! -f .env ]; then
  log "writing .env for local development ($DB_ENGINE)"
  SECRET=$($PY -c "import secrets; print(secrets.token_urlsafe(40))")
  DBPASS=$($PY -c "import secrets; print(secrets.token_urlsafe(16))")
  {
    echo "DEBUG=true"
    echo "SECRET_KEY=$SECRET"
    echo "APP_URL=http://localhost:8000"
    echo "ALLOWED_HOSTS=localhost,127.0.0.1,testserver"
    echo "EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend"
    echo "STORAGE_BACKEND=local"
    echo "ADMIN_NOTIFICATION_EMAILS=admin@skyleon.local"
    if [ "$DB_ENGINE" = "mysql" ]; then
      printf 'DB_ENGINE=mysql\nDB_NAME=skyleon\nDB_USER=skyleon\nDB_PASSWORD=%s\nDB_HOST=127.0.0.1\nDB_PORT=3306\n' "$DBPASS"
    else
      echo "DB_ENGINE=sqlite"
    fi
  } > .env
fi

if grep -q '^DB_ENGINE=mysql' .env; then
  log "starting MariaDB"
  service mariadb start >/dev/null 2>&1 || service mysql start >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do mariadb -uroot -e "SELECT 1" >/dev/null 2>&1 && break; sleep 1; done
  DBNAME=$(grep '^DB_NAME=' .env | cut -d= -f2-)
  DBUSER=$(grep '^DB_USER=' .env | cut -d= -f2-)
  DBPASS=$(grep '^DB_PASSWORD=' .env | cut -d= -f2-)
  mariadb -uroot <<SQL
CREATE DATABASE IF NOT EXISTS \`${DBNAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DBUSER}'@'localhost' IDENTIFIED BY '${DBPASS}';
CREATE USER IF NOT EXISTS '${DBUSER}'@'127.0.0.1' IDENTIFIED BY '${DBPASS}';
GRANT ALL ON \`${DBNAME}\`.* TO '${DBUSER}'@'localhost';
GRANT ALL ON \`${DBNAME}\`.* TO '${DBUSER}'@'127.0.0.1';
GRANT ALL ON \`test\_${DBNAME}%\`.* TO '${DBUSER}'@'localhost';
GRANT ALL ON \`test\_${DBNAME}%\`.* TO '${DBUSER}'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
fi

# 4. Schema + demo data --------------------------------------------------------
$PY manage.py migrate --noinput >/dev/null
$PY manage.py createcachetable >/dev/null
if [ "$($PY manage.py shell -c "from apps.accounts.models import User; print(User.objects.exists())" 2>/dev/null | tail -1)" != "True" ]; then
  log "empty database — loading demo data (password Demo@12345)"
  $PY manage.py seed_demo >/dev/null
fi

# 5. Dev server ------------------------------------------------------------------
if ! curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/healthz/; then
  log "starting the dev server on :8000"
  setsid nohup $PY manage.py runserver 0.0.0.0:8000 > /tmp/skyleon-runserver.log 2>&1 < /dev/null &
  for _ in $(seq 1 20); do curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/healthz/ && break; sleep 1; done
fi
log "ready — http://127.0.0.1:8000 (log: /tmp/skyleon-runserver.log)"
