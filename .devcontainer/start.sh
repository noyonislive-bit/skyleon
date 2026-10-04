#!/usr/bin/env bash
# Runs every time you open (or re-open) the Codespace: brings the preview up to date, then starts the
# website on port 8000. A stopped Codespace never needs to be re-created — just open it again.
cd "$(dirname "$0")/.."

echo ""
echo "  Updating the preview to the latest code…"
# 1. Latest code from GitHub (only when you have no local edits, so nothing of yours is overwritten).
if [ -d .git ] && [ -z "$(git status --porcelain --untracked-files=no)" ]; then
  git pull --ff-only --quiet 2>/dev/null && echo "  ✔ code updated ($(git log -1 --format=%h))" || echo "  (could not pull — using the code already here)"
fi
# 2. New packages and database changes that the new code needs.
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
python manage.py migrate --noinput >/dev/null && echo "  ✔ database up to date"
python manage.py createcachetable >/dev/null 2>&1
if [ "$(python manage.py shell -c "from apps.accounts.models import User; print(User.objects.exists())" 2>/dev/null | tail -1)" != "True" ]; then
  python manage.py seed_demo >/dev/null && echo "  ✔ demo data loaded"
fi

# 3. Start the website (unless it is already running from an earlier attach).
if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/healthz/; then
  echo "  The website is already running on port 8000 — open the 'Ports' tab → 8000 → globe icon."
  exit 0
fi
echo ""
echo "  Skyloon AI is starting on port 8000 — open the 'Ports' tab if the browser does not open automatically."
echo "  Demo logins (password Demo@12345): admin@skyleon.local, pm@skyleon.local, trainer@skyleon.local, employee1@skyleon.local"
echo ""
exec python manage.py runserver 0.0.0.0:8000
