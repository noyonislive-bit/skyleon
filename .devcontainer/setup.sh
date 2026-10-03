#!/usr/bin/env bash
# Runs once when the Codespace is created: installs dependencies and creates a demo database (SQLite).
set -euo pipefail
cd "$(dirname "$0")/.."

# ffmpeg lets the demo seed generate local sample videos (optional — falls back to an online sample video)
(sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg >/dev/null) || echo "ffmpeg not installed — using online sample videos"

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cat > .env <<ENV
DEBUG=true
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(40))")
DB_ENGINE=sqlite
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
ALLOWED_HOSTS=localhost,127.0.0.1,.app.github.dev,.githubpreview.dev
CSRF_TRUSTED_ORIGINS=https://*.app.github.dev,https://*.githubpreview.dev,http://localhost:8000
ENV
fi

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py seed_demo
echo "Setup complete — the site starts automatically on port 8000."
