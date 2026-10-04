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

## Source of truth (how a guide is built)

The original documentation and the original videos are the **source of truth**. The guides are not a
summary — they must let an employee do the real work correctly from either the video or the Bangla text.

**Order of authority:** Original document → Original video → Actual workflow → Bangla documentation → Portal UI.

When a document link is given, whoever builds the guide (trainer or Claude):

1. Reads **every section** and understands every instruction.
2. Follows **which button is pressed when**, in the original order — the **sequence of steps is never changed**.
3. Keeps **every rule** exactly as written — a rule is never reworded into something weaker or stricter.
4. Keeps **all relevant examples** from the document (use `> [!EXAMPLE]` boxes).
5. **Watches every embedded video.** What the video actually shows is the reference for the workflow;
   each step points to the exact part of the video it describes (`video_start` – `video_end`), so the
   video and the Bangla text show the same thing.
6. Turns every mistake the document or video says counts as a **Task Error** into a **Task Error example**
   (see below) — never leaves it as a passing remark.
7. Only the **presentation** (UI/UX, wording into natural Bangla, layout) is improved. Nothing is added,
   removed or reordered in the workflow itself. Technical terms stay in English when that is clearer
   (see `docs/BANGLA_STYLE.md`).

**Verification.** Every step and every Task Error example has a *Verified against the original* mark (editor →
“Verify”). A trainer sets it only after comparing the Bangla text with the original text **and** the video segment.
Editing the content later clears the mark automatically. The editor shows “x of y verified”, and publishing a
guide with unverified items needs an explicit “Publish anyway”. `source_ref` records where each item comes from
(e.g. “Doc §2 Splitting rules, point 3 · video 01:20–02:05”) — visible to staff only.

## Task Error examples

A mistake shown in the original as causing a **Task Error** becomes its own red card in the guide:

* headline *“এই কাজটি এভাবে ভুল করলে Task Error হিসেবে গণ্য হবে”*
* **কী ভুল হয়েছে** — what was done wrong
* **কেন এটা ভুল** — which rule it breaks
* **কীভাবে এড়াবেন** — what to check while working
* **সঠিক পদ্ধতি** — the correct method, as the original shows it
* the part of the **original video** that shows the mistake (start – end), and optionally the original English text

Examples are attached to the step they belong to (shown inside that step, below its explanation) or added as
general examples for the whole guide. Every guide with examples also gets a **“সব Task Error উদাহরণ”** block
(`#task-errors`) listing all of them, linked from the table of contents and the guide header, so employees can
review every Task Error before they start work.

## Videos and segments (admin)

Every step and Task Error example can use **one video**, chosen in its form:

* **Original link** — YouTube, Vimeo, Google Drive, Loom, Stream/SharePoint, Lark, a direct MP4/WebM or an HLS link.
  Use this for every video that comes from the source documents (never downloaded or re-hosted).
* **Uploaded video** — upload a file (or reuse one already uploaded) to our private storage; it streams to employees
  through signed, per-viewer links. Use this for videos you recorded yourselves.

**Video segments** (editor → *Video segments*, or *Set start / end on the video* in a step form) is one screen for the
whole guide: pick a video (used in the guide, from the uploaded library, a pasted link or a new upload), play it, select a
step or Task Error example and press **[** where its part starts and **]** where it ends (or drag the edges of its block on
the timeline, or type m:ss). **P** plays the selected part, ↑/↓ moves between items, *Use this video* assigns the current
video to an item. Saving clears the *verified* mark of every changed item, so it is checked against the original again.
YouTube, Vimeo, uploaded and direct/HLS videos report their time to the editor; for Drive, Lark, Loom and Stream players
type the times you read in the player.

## Importing a document (Word / Markdown)

Admin → Work guides → **Import a document**: upload the document exported from Lark (⋯ → Download as → Word or
Markdown). Its headings become sections and steps **in the original order**; each step keeps the original English text
(*মূল ইংরেজি*) and the first video link in it. The guide is created as a draft — nothing is translated or invented. Then,
for each step: write the Bangla text (the editor marks steps with *Bangla missing*), set the video segment, add the Task
Error examples the document/video shows, and verify. Until a step has Bangla text, employees see the original English
instruction with a note.

## Videos — original links only

Videos are **never downloaded or stored on our server**. Paste the original link and it is embedded:
YouTube, Vimeo, Google Drive, Loom, Microsoft Stream/SharePoint, Lark/Feishu, direct `.mp4/.webm/.mov`,
or HLS `.m3u8`. Links from services that require a login (e.g. Lark files) only play for viewers who are
signed in to that service with access — an “Open original” link is always shown under the player.

## Managing guides (Admin → Work guides)

* Create a guide, add sections and steps, reorder, publish/unpublish, preview as employee, see progress per employee.
* Step editor: Bangla explanation with a callout cheat-sheet, original English text, video link with live
  detection and preview, the video part the step describes (from – to), “which button does what” rows,
  source reference and the “Verified against the original” tick.
* Task Error examples: shield button on a step (or “General example”), with the four parts above, the original
  video segment, source reference and verification.

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
progress on steps whose anchors still exist (and the verification mark of items whose content is unchanged).
Steps accept `video_end`, `source_ref` and `task_errors`; general examples go in a top-level `task_errors` list. Every guide can be exported back to JSON from its editor.
The full format is shown on the import page; a working example is `apps/guides/fixtures/sample_guide.json`.
