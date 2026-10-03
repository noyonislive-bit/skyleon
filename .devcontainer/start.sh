#!/usr/bin/env bash
# Runs every time you open the Codespace: starts the website on port 8000 (Codespaces opens it in the browser).
cd "$(dirname "$0")/.."
echo ""
echo "  Skyloon AI is starting on port 8000 — open the 'Ports' tab if the browser does not open automatically."
echo "  Demo logins (password Demo@12345): admin@skyleon.local, pm@skyleon.local, trainer@skyleon.local, employee1@skyleon.local"
echo ""
exec python manage.py runserver 0.0.0.0:8000
