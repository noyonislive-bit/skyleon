"""
Browser smoke test across the public site, employee portal, practice lab and admin panel.

    python tests/e2e/smoke.py [--base http://localhost:8000]

Requires demo data (python manage.py seed_demo) and Playwright for Python.
Set PW_CHROMIUM=/path/to/chrome to use a specific Chromium build.
"""

import argparse
import asyncio
import os
import sys

from playwright.async_api import async_playwright

PUBLIC = ["/", "/services/", "/services/video-annotation/", "/industries/", "/solutions/", "/solutions/video-segmentation/",
          "/capability/", "/quality-assurance/", "/platforms-and-workflow/", "/security/", "/about/", "/careers/",
          "/contact/", "/request-a-quote/", "/privacy/", "/terms/", "/robots.txt", "/sitemap.xml", "/login/", "/signup/",
          "/client/login/"]
EMPLOYEE = ["/portal/", "/portal/onboarding/", "/portal/projects/", "/portal/training/", "/portal/feedback/", "/portal/tests/",
            "/portal/results/", "/portal/announcements/", "/portal/meetings/", "/portal/notifications/", "/portal/profile/",
            "/portal/practice/", "/portal/practice/1/", "/portal/guides/"]
STAFF = ["/admin/", "/admin/employees/", "/admin/projects/", "/admin/tutorials/", "/admin/training/",
         "/admin/feedback/", "/admin/feedback/tracking/", "/admin/tests/", "/admin/reports/", "/admin/announcements/",
         "/admin/meetings/", "/admin/practice/", "/admin/guides/"]
SUPER = ["/admin/applicants/", "/admin/leads/", "/admin/messages/", "/admin/emails/", "/admin/settings/", "/admin/practice/settings/", "/django-admin/"]
ROLES = {
    None: PUBLIC,
    "employee1@skyleon.local": EMPLOYEE,
    "trainer@skyleon.local": STAFF,
    "admin@skyleon.local": STAFF + SUPER,
}
IGNORED_CONSOLE = ("favicon", "net::ERR_", "Failed to load resource: net::")


async def run(base):
    failures = []
    async with async_playwright() as p:
        exe = os.environ.get("PW_CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
        browser = await p.chromium.launch(executable_path=exe)
        for email, paths in ROLES.items():
            ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
            page = await ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" and not any(s in m.text for s in IGNORED_CONSOLE) else None)
            if email:
                await page.goto(base + "/login/")
                await page.fill("#id_identifier", email)
                await page.fill("#id_password", "Demo@12345")
                await page.click("button[type=submit]")
                await page.wait_for_load_state("networkidle")
            for path in paths:
                errors.clear()
                resp = await page.goto(base + path, wait_until="networkidle")
                status = resp.status if resp else 0
                ok = status == 200 and not errors
                print(f"{'OK ' if ok else 'ERR'} {status} {email or 'anonymous':28} {path} {'; '.join(errors)[:200]}")
                if not ok:
                    failures.append((email, path, status, errors[:3]))
            await ctx.close()
        await browser.close()
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    sys.exit(asyncio.run(run(ap.parse_args().base.rstrip("/"))))
