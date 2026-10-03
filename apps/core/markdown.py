"""
Safe Markdown rendering for staff-authored content (guidelines, feedback
explanations, announcements). Raw HTML is disabled and link targets are
restricted to safe schemes, so the output can be marked safe in templates.
"""

import re

import markdown as md
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

SAFE_URL = re.compile(r"^(https?:|mailto:|tel:|/|#)", re.IGNORECASE)


class _SafeLinks(Treeprocessor):
    def run(self, root):
        for el in root.iter():
            if el.tag == "a":
                href = el.get("href", "")
                if not SAFE_URL.match(href):
                    el.set("href", "#")
                if href.startswith("http"):
                    el.set("target", "_blank")
                    el.set("rel", "noopener noreferrer nofollow")
            if el.tag == "img":
                src = el.get("src", "")
                if not SAFE_URL.match(src):
                    el.set("src", "")
                el.set("loading", "lazy")


CALLOUTS = {
    "NOTE": "Note", "TIP": "Tip", "RULE": "Rule", "WARNING": "Warning",
    "IMPORTANT": "Important", "EXAMPLE": "Example", "STEP": "Step",
}
CALLOUT_RE = re.compile(r"^\s*\[!(%s)\][ \t]*([^\n]*)" % "|".join(CALLOUTS), re.IGNORECASE)


class _Callouts(Treeprocessor):
    """
    GitHub-style alerts: `> [!RULE] Optional title` → <div class="callout callout-rule">.
    Python-Markdown merges adjacent quotes, so every paragraph starting with a
    marker opens a new callout.
    """

    def run(self, root):
        import xml.etree.ElementTree as etree

        parents = {child: parent for parent in root.iter() for child in parent}
        for bq in list(root.iter("blockquote")):
            children = list(bq)
            if not any(c.tag == "p" and c.text and CALLOUT_RE.match(c.text) for c in children):
                continue
            groups, current = [], None
            for child in children:
                m = CALLOUT_RE.match(child.text or "") if child.tag == "p" else None
                if m:
                    kind = m.group(1).upper()
                    current = etree.Element("div")
                    current.set("class", f"callout callout-{kind.lower()}")
                    head = etree.SubElement(current, "p")
                    head.set("class", "callout-title")
                    head.text = m.group(2).strip() or CALLOUTS[kind]
                    child.text = child.text[m.end():].lstrip("\n")
                    if len(child) and child[0].tag == "br" and not child.text.strip():
                        br = child[0]
                        child.text = (br.tail or "").lstrip("\n")
                        child.remove(br)
                    groups.append(current)
                    if child.text.strip() or len(child):
                        current.append(child)
                    continue
                if current is None:
                    current = etree.Element("blockquote")
                    groups.append(current)
                current.append(child)
            parent = parents.get(bq, root)
            idx = list(parent).index(bq)
            parent.remove(bq)
            for offset, el in enumerate(groups):
                el.tail = "\n"
                parent.insert(idx + offset, el)


class _NoRawHtml(Extension):
    def extendMarkdown(self, m):
        m.preprocessors.deregister("html_block")
        m.inlinePatterns.deregister("html")
        m.treeprocessors.register(_SafeLinks(m), "safe_links", 0)
        m.treeprocessors.register(_Callouts(m), "callouts", 1)


def render_markdown(text: str | None) -> str:
    if not text:
        return ""
    return md.markdown(
        text,
        extensions=[_NoRawHtml(), "extra", "sane_lists", "nl2br"],
        output_format="html",
    )
