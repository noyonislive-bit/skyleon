# Work guides (Bangla step-by-step documents)

Employee portal → **Work guides** (`/portal/guides/`) turns long English work documents
(e.g. *Video Splitting*, *Description writing*) into Bangla, step-by-step training:

**Guide → Section → Step → Video → Description → Next step**

* **Document view** `/portal/guides/<slug>/` — sticky table of contents, the section/step in view is
  highlighted (scrollspy), smooth scrolling, deep links (`/portal/guides/<slug>/#<anchor>`), search,
  reading progress, “বুঝেছি” (understood) per step, mobile TOC drawer.
* **Step-by-step view** `/portal/guides/<slug>/step/<anchor>/` — one step per page with Previous / Next
  (← / → keys) and “বুঝেছি ও পরের ধাপ”.
* Each step has a **video panel** (from the original link) and a **description panel** (Bangla Markdown with
  rule / tip / warning boxes, a “কোন বোতামে কী হয়” table and an optional “মূল ইংরেজি দেখুন” toggle).

## Videos — original links only

Videos are **never downloaded or stored on our server**. Paste the original link and it is embedded:
YouTube, Vimeo, Google Drive, Loom, Microsoft Stream/SharePoint, Lark/Feishu, direct `.mp4/.webm/.mov`,
or HLS `.m3u8`. Links from services that require a login (e.g. Lark files) only play for viewers who are
signed in to that service with access — an “Open original” link is always shown under the player.

## Managing guides (Admin → Work guides)

* Create a guide, add sections and steps, reorder, publish/unpublish, preview as employee, see progress per employee.
* Step editor: Bangla explanation with a callout cheat-sheet, original English text, video link with live
  detection and preview, “which button does what” rows.

Callout syntax inside explanations:

```markdown
> [!RULE] নিয়ম
> হাত ফ্রেমের বাইরে গেলে ক্লিপ শেষ করুন।
```

Types: `RULE`, `TIP`, `WARNING`, `IMPORTANT`, `NOTE`, `EXAMPLE`, `STEP`.

## Import / export (JSON)

```bash
python manage.py import_guide path/to/guide.json [--replace] [--publish] [--dry-run]
```

or Admin → Work guides → **Import JSON**. `--replace` rebuilds sections and steps but keeps employees'
progress on steps whose anchors still exist. Every guide can be exported back to JSON from its editor.
The full format is shown on the import page; a working example is `apps/guides/fixtures/sample_guide.json`.
