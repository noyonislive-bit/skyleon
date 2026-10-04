# Skyloon AI — preview in Codespaces

The website starts automatically on **port 8000** (see the terminal below). Every time the Codespace is opened it first updates itself to the latest code and database — a stopped Codespace never needs to be created again: github.com/codespaces → your codespace → *Open in browser*. If the browser tab did not open,
click the **Ports** tab → port 8000 → the globe icon (Open in Browser).

| Area | Path |
|---|---|
| Public website | `/` |
| Login (employees & staff) | `/login/` |
| Employee portal | `/portal/` |
| Practice Lab (clipping tool) | `/portal/practice/` |
| Admin panel | `/admin/` |

Demo accounts — password **`Demo@12345`**:

| Role | Email |
|---|---|
| Super Admin | `admin@skyleon.local` |
| Project Manager | `pm@skyleon.local` |
| Trainer / QA | `trainer@skyleon.local` |
| Employees | `employee1@skyleon.local` … `employee8@skyleon.local` |
| Pending signup | `new.member1@skyleon.local` |
| Client | `client@northwind.example` |

Emails are printed in the terminal instead of being sent. Data is a local SQLite demo database —
to start fresh run `rm db.sqlite3 && bash .devcontainer/setup.sh`.

The preview link is private to your GitHub account by default. To show it to someone else, right-click
port 8000 in the **Ports** tab → Port Visibility → Public (turn it back to Private afterwards).

## Staying up to date and online

* While the Codespace is open, `supervisor.sh` restarts the website if it ever stops and pulls new code from
  GitHub every few minutes (when you have no local edits) — new features appear without stopping anything.
  Log: `/tmp/skyloon-supervisor.log`.
* GitHub stops an idle Codespace after its **idle timeout** (30 minutes by default). Raise it to the maximum
  (**240 minutes**) in github.com → Settings → Codespaces → *Default idle timeout*, and set *Default retention
  period* to **30 days** so a stopped Codespace is never deleted. A stopped Codespace is reopened from
  github.com/codespaces — never re-create it.
* For a site that is online 24 hours a day, deploy it to your hosting: `docs/DEPLOY_CPANEL_BN.md`.

