# Skyloon AI — preview in Codespaces

The website starts automatically on **port 8000** (see the terminal below). If the browser tab did not open,
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
