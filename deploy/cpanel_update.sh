#!/bin/bash
# Update a running cPanel installation to the latest code (run inside the app's virtualenv):
#   source /home/<cpuser>/virtualenv/<app>/3.11/bin/activate && cd /home/<cpuser>/<app> && bash deploy/cpanel_update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -n "${VIRTUAL_ENV:-}" ] || { echo "Activate the app's virtualenv first (cPanel → Setup Python App shows the command)."; exit 1; }
PY="$VIRTUAL_ENV/bin/python"
if [ -d .git ]; then git pull --ff-only; fi
"$PY" -m pip install --quiet -r requirements.txt
"$PY" manage.py collectstatic --noinput >/dev/null   # before migrate: pages need the static manifest
"$PY" manage.py migrate --noinput
"$PY" manage.py createcachetable
mkdir -p tmp && touch tmp/restart.txt
echo "✔ Updated and restarted."
