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


class _NoRawHtml(Extension):
    def extendMarkdown(self, m):
        m.preprocessors.deregister("html_block")
        m.inlinePatterns.deregister("html")
        m.treeprocessors.register(_SafeLinks(m), "safe_links", 0)


def render_markdown(text: str | None) -> str:
    if not text:
        return ""
    return md.markdown(
        text,
        extensions=[_NoRawHtml(), "extra", "sane_lists", "nl2br"],
        output_format="html",
    )
