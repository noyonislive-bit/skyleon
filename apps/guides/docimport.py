"""
Turn a work document exported from Lark / Feishu (or any editor) into a draft guide.

    data = document_to_guide(raw_bytes, filename, slug="video-splitting", title="ভিডিও স্প্লিটিং গাইড", …)
    import_guide(data)                        # the normal JSON importer does the rest

Supported files: Word (.docx — Lark: ⋯ → Download as → Word) and Markdown (.md / .txt).
Nothing is translated or invented: the document's structure becomes sections and steps in the
original order, its text is kept as each step's ORIGINAL ENGLISH (`body_en`), and video links
in a step become that step's video (original link, never re-hosted). The Bangla text is then
written step by step in the editor (or by Claude), next to the original.

Structure: the first heading becomes the guide's English title when it is the only heading at
its level; the next heading level becomes sections and the one below it steps. A section
without sub-headings becomes a single step. Deeper headings stay inside the step text.
"""

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

from .video import embed_info

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
MAX_BYTES = 20 * 1024 * 1024


class DocumentImportError(Exception):
    pass


# ── Word (.docx) → Markdown ─────────────────────────────────────────────────

def docx_to_markdown(raw: bytes) -> str:
    try:
        zf = zipfile.ZipFile(BytesIO(raw))
        doc = ET.fromstring(zf.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise DocumentImportError("This is not a readable Word (.docx) file.") from exc
    rels = {}
    try:
        for rel in ET.fromstring(zf.read("word/_rels/document.xml.rels")).iter(f"{REL}Relationship"):
            rels[rel.get("Id")] = rel.get("Target", "")
    except (KeyError, ET.ParseError):
        pass
    levels = _heading_styles(zf)
    body = doc.find(f"{W}body")
    lines: list[str] = []
    for block in list(body) if body is not None else []:
        if block.tag == f"{W}p":
            lines.append(_paragraph(block, rels, levels))
        elif block.tag == f"{W}tbl":
            for row in block.iter(f"{W}tr"):
                cells = [" ".join(_paragraph(p, rels, levels) for p in tc.iter(f"{W}p")).strip() for tc in row.iter(f"{W}tc")]
                if any(cells):
                    lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
            lines.append("")
    return "\n".join(lines)


def _heading_styles(zf) -> dict:
    """styleId → heading level, from styles.xml ("heading 2", "Title", or an outline level)."""
    out = {}
    try:
        styles = ET.fromstring(zf.read("word/styles.xml"))
    except (KeyError, ET.ParseError):
        return out
    for st in styles.iter(f"{W}style"):
        sid = st.get(f"{W}styleId") or ""
        name_el = st.find(f"{W}name")
        name = (name_el.get(f"{W}val") if name_el is not None else sid or "").strip().lower()
        m = re.match(r"^heading\s*(\d)$", name)
        if m:
            out[sid] = int(m.group(1))
        elif name == "title":
            out[sid] = 1
        else:
            lvl = st.find(f"{W}pPr/{W}outlineLvl")
            if lvl is not None and (lvl.get(f"{W}val") or "").isdigit() and int(lvl.get(f"{W}val")) < 6:
                out[sid] = int(lvl.get(f"{W}val")) + 1
    return out


def _paragraph(p, rels, levels) -> str:
    ppr = p.find(f"{W}pPr")
    level = 0
    is_list = False
    if ppr is not None:
        style = ppr.find(f"{W}pStyle")
        sid = style.get(f"{W}val") if style is not None else ""
        level = levels.get(sid, 0)
        if not level:
            m = re.match(r"^(?:heading|Heading)\s*(\d)$", sid or "")
            level = int(m.group(1)) if m else 0
        outline = ppr.find(f"{W}outlineLvl")
        if not level and outline is not None and (outline.get(f"{W}val") or "").isdigit() and int(outline.get(f"{W}val")) < 6:
            level = int(outline.get(f"{W}val")) + 1
        is_list = ppr.find(f"{W}numPr") is not None
    parts = []
    for child in p:
        if child.tag == f"{W}r":
            parts.append(_run(child))
        elif child.tag == f"{W}hyperlink":
            text = "".join(_run(r) for r in child.iter(f"{W}r")).strip()
            url = rels.get(child.get(f"{R}id") or "", "")
            if url.startswith("http"):
                parts.append(f"[{text or url}]({url})")
            else:
                parts.append(text)
    text = "".join(parts).strip()
    if not text:
        return "*(ছবি / ফাইল — মূল ডকুমেন্টে দেখুন)*" if p.find(f".//{W}drawing") is not None else ""
    if level:
        return "#" * min(level, 6) + " " + text.replace("**", "")
    return ("- " + text) if is_list else text


def _run(r) -> str:
    out = []
    for c in r:
        if c.tag == f"{W}t":
            out.append(c.text or "")
        elif c.tag == f"{W}tab":
            out.append(" ")
        elif c.tag in (f"{W}br", f"{W}cr"):
            out.append("\n")
    text = "".join(out)
    rpr = r.find(f"{W}rPr")
    if text.strip() and rpr is not None and rpr.find(f"{W}b") is not None and rpr.find(f"{W}b").get(f"{W}val") not in ("0", "false"):
        lead, core, trail = re.match(r"^(\s*)(.*?)(\s*)$", text, re.S).groups()
        return f"{lead}**{core}**{trail}"
    return text


# ── Markdown → guide JSON ───────────────────────────────────────────────────

def is_video_link(url: str) -> bool:
    info = embed_info(url)
    if info is None or info["kind"] == "link":
        return False
    if info["provider"] == "lark":  # only Lark files / minutes are videos — wiki/docx links are documents
        return bool(re.search(r"/(file|minutes|drive/file)/", url))
    return True


def markdown_to_outline(md: str):
    """[(level, title, [lines])] — every heading with the text that follows it (text before the first heading → level 0)."""
    blocks = [[0, "", []]]
    in_code = False
    for line in md.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else HEADING_RE.match(line)
        if m and m.group(2).strip():
            blocks.append([len(m.group(1)), m.group(2).strip().replace("**", ""), []])
        else:
            blocks[-1][2].append(line)
    return blocks


def _text(lines) -> str:
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def document_to_guide(raw: bytes, filename: str, *, slug: str, title: str = "", kind: str = "general",
                      project_code=None, source_url: str = "") -> dict:
    if len(raw) > MAX_BYTES:
        raise DocumentImportError("The file is too large (max 20 MB).")
    name = (filename or "").lower()
    if name.endswith(".docx"):
        md = docx_to_markdown(raw)
    elif name.endswith((".md", ".markdown", ".txt")):
        try:
            md = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentImportError("The Markdown file is not UTF-8 text.") from exc
    else:
        raise DocumentImportError("Upload a Word (.docx) or Markdown (.md) file — in Lark: ⋯ → Download as → Word.")

    blocks = markdown_to_outline(md)
    preface = _text(blocks[0][2])
    heads = blocks[1:]
    if not heads:
        raise DocumentImportError("No headings found. Sections and steps are taken from the document's headings (Heading 1/2/3).")
    title_en = ""
    levels = sorted({b[0] for b in heads})
    if sum(1 for b in heads if b[0] == levels[0]) == 1 and len(levels) > 1 and heads[0][0] == levels[0]:
        title_en = heads[0][1]
        preface = _text([preface, _text(heads[0][2])])
        heads = heads[1:]
        levels = levels[1:]
    sec_level = levels[0]
    step_level = levels[1] if len(levels) > 1 else None

    sections = []
    if preface:
        sections.append({"title": "ভূমিকা", "title_en": "Introduction", "steps": [_step("Overview", [preface])], "_lines": []})
    for level, head, lines in heads:
        if level == sec_level:
            sections.append({"title": head, "title_en": head, "steps": [], "_lines": list(lines)})
        elif not sections:
            sections.append({"title": "ভূমিকা", "title_en": "Introduction", "steps": [], "_lines": []})
            sections[-1]["steps"].append(_step(head, lines))
        elif step_level is not None and level == step_level:
            sections[-1]["steps"].append(_step(head, lines))
        else:  # deeper heading: stays inside the current step (or section text)
            target = sections[-1]["steps"][-1]["_lines"] if sections[-1]["steps"] else sections[-1]["_lines"]
            target += ["", "#### " + head, *lines]
    for sec in sections:
        own = sec.pop("_lines", [])
        if not sec["steps"]:
            sec["steps"].append(_step(sec["title_en"], own))
        elif _text(own):  # section text before its first step: kept, as an extra first step
            sec["steps"].insert(0, _step(f"{sec['title_en']} — overview", own))
        for st in sec["steps"]:
            _finish(st)
    return {
        "slug": slug, "title": title or title_en or slug, "title_en": title_en, "kind": kind,
        "summary": "", "source_url": source_url, "project_code": project_code or None, "sections": sections,
    }


def _step(title, lines) -> dict:
    return {"title": title[:200], "_lines": list(lines)}


def _finish(st: dict) -> dict:
    """Text and video of a step, once all its lines (incl. deeper headings) are collected."""
    text = _text(st.pop("_lines"))
    video = next((u.rstrip(".,;") for u in URL_RE.findall(text) if is_video_link(u.rstrip(".,;"))), "")
    st.update(body="", body_en=text, video_url=video, source_ref=f"Original: “{st['title'][:120]}”")
    return st


def outline_preview(data: dict) -> list[dict]:
    return [{"title": s["title_en"] or s["title"], "steps": [{"title": st["title"], "video": bool(st["video_url"]),
                                                             "chars": len(st["body_en"])} for st in s["steps"]]}
            for s in data["sections"]]
