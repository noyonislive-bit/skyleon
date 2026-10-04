#!/usr/bin/env bash
# Keeps the Codespace preview running and up to date while the Codespace is open:
#   • every minute: if the website doesn't answer, it is (re)started;
#   • every few minutes: if GitHub has new commits on this branch (and you have no local edits),
#     they are pulled, new packages installed and the database migrated — the dev server then
#     reloads the new code by itself. No need to stop, rebuild or re-create anything.
# Started by start.sh (only one copy runs). Log: /tmp/skyloon-supervisor.log
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
CHECK_EVERY="${CHECK_EVERY:-60}"        # seconds between health checks
UPDATE_EVERY="${UPDATE_EVERY:-3}"       # look for updates every N health checks
SERVER_LOG="${SERVER_LOG:-/tmp/skyloon-server.log}"
LOG="${SUPERVISOR_LOG:-/tmp/skyloon-supervisor.log}"

exec 9>"/tmp/skyloon-supervisor-$PORT.lock"
flock -n 9 || exit 0   # already running

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

serve() {
  curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/healthz/" && return
  log "website not answering — starting it on :$PORT"
  setsid nohup python manage.py runserver "0.0.0.0:$PORT" >> "$SERVER_LOG" 2>&1 < /dev/null &
  for _ in $(seq 1 20); do curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/healthz/" && return; sleep 1; done
}

update() {
  [ -d .git ] || return
  git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1 || return   # no upstream branch
  git fetch --quiet 2>/dev/null || return
  [ "$(git rev-parse HEAD)" = "$(git rev-parse "@{u}")" ] && return                  # already up to date
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    log "new code on GitHub, but you have local edits — not updating automatically"; return
  fi
  local req_before; req_before=$(git rev-parse HEAD:requirements.txt 2>/dev/null)
  git pull --ff-only --quiet 2>>"$LOG" || { log "git pull failed"; return; }
  if [ "$req_before" != "$(git rev-parse HEAD:requirements.txt 2>/dev/null)" ]; then
    python -m pip install --quiet --disable-pip-version-check -r requirements.txt >> "$LOG" 2>&1
  fi
  python manage.py migrate --noinput >> "$LOG" 2>&1
  python manage.py createcachetable >/dev/null 2>&1
  log "updated to $(git log -1 --format='%h %s')"
}

log "supervisor started (port $PORT)"
n=0
while true; do
  [ $((n % UPDATE_EVERY)) -eq 0 ] && update
  serve
  n=$((n + 1))
  sleep "$CHECK_EVERY"
done
