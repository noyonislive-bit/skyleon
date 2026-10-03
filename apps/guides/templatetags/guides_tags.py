"""
Template helpers for work guides.

  {% load guides_tags %}
  {{ 12|bn }}                         → ১২ (Bangla digits)
  {{ step.body|guide_md }}            → Markdown with Bangla default callout titles
  {% action_key action %}             → <kbd>N</kbd> / <kbd>Shift</kbd>+<kbd>→</kbd> or a button-style chip
  {% guide_video info title=… %}      → player for an embed_info() dict (iframe / video / hls / link)
"""

import re

from django import template
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from apps.core.markdown import render_markdown

from ..services import bn as _bn
from ..video import describe

register = template.Library()

CALLOUT_TITLES_BN = {
    "RULE": "নিয়ম", "TIP": "টিপস", "WARNING": "সতর্কতা", "NOTE": "নোট",
    "IMPORTANT": "জরুরি", "EXAMPLE": "উদাহরণ", "STEP": "ধাপ",
}
_BARE_CALLOUT = re.compile(r"^(\s*>\s*\[!(%s)\])[ \t]*$" % "|".join(CALLOUT_TITLES_BN), re.IGNORECASE | re.MULTILINE)


@register.filter
def bn(value):
    return "" if value is None else _bn(value)


@register.filter(is_safe=True)
def guide_md(text):
    """Markdown → HTML; callouts without a title get a Bangla one (> [!RULE] → “নিয়ম”)."""
    if not text:
        return ""
    text = _BARE_CALLOUT.sub(lambda m: f"{m.group(1)} {CALLOUT_TITLES_BN[m.group(2).upper()]}", text)
    return mark_safe(render_markdown(text))


# ── Keys & buttons ──────────────────────────────────────────────────────────

KEY_NAMES = {
    "space", "spacebar", "enter", "return", "esc", "escape", "tab", "shift", "ctrl", "control", "alt", "option",
    "cmd", "command", "meta", "win", "delete", "del", "backspace", "home", "end", "pageup", "pagedown", "insert",
    "up", "down", "left", "right", "arrowleft", "arrowright", "arrowup", "arrowdown", "capslock", "fn",
}
KEY_PRETTY = {"arrowleft": "←", "arrowright": "→", "arrowup": "↑", "arrowdown": "↓", "left": "←", "right": "→", "up": "↑", "down": "↓"}


def _is_key(part: str) -> bool:
    p = part.strip().lower()
    return bool(p) and (len(p) <= 2 or p in KEY_NAMES or bool(re.fullmatch(r"f\d{1,2}", p)) or p in "←→↑↓")


def split_key(value: str):
    """'Shift+→ / Delete' → [['Shift', '→'], ['Delete']] (or None when it is a button label)."""
    value = (value or "").strip()
    if not value:
        return None
    if len(value) <= 2:
        return [[KEY_PRETTY.get(value.lower(), value)]]
    alternatives = [a.strip() for a in re.split(r"\s+(?:/|or|অথবা)\s+", value) if a.strip()]
    combos = []
    for alt in alternatives:
        parts = [alt] if alt == "+" else [p.strip() for p in re.split(r"(?<=.)\+(?=.)", alt)]
        if not all(_is_key(p) for p in parts):
            return None
        combos.append([KEY_PRETTY.get(p.lower(), p) for p in parts])
    return combos


@register.simple_tag
def action_key(action):
    key = str((action or {}).get("key") or "").strip()
    kind = (action or {}).get("type")
    combos = None if kind == "button" else split_key(key)
    if combos is None or kind == "button":
        return format_html('<span class="g-uibtn">{}</span>', key)
    out = []
    for i, combo in enumerate(combos):
        if i:
            out.append(mark_safe('<span class="g-key-sep">/</span>'))
        out.append(format_html_join(mark_safe('<span class="g-key-plus">+</span>'), '<kbd class="g-kbd">{}</kbd>', ((k,) for k in combo)))
    return mark_safe("".join(str(x) for x in out))


# ── Video ───────────────────────────────────────────────────────────────────

@register.inclusion_tag("guides/_video.html")
def guide_video(info, title="", caption="", compact=False):
    return {"info": info, "title": title, "caption": caption, "compact": compact}


@register.filter
def video_describe(info):
    return describe(info)
