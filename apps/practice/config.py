"""
Tool configuration, editable in Admin → Practice lab → Tool settings, so the
practice tool can be matched to the production tool without code changes.
"""

from apps.core.site_settings import get_setting, set_setting

# action → list of keys (KeyboardEvent.key values; "Space" means " ")
DEFAULT_SHORTCUTS = {
    "play_pause": ["Space"],
    "cut": ["n"],
    "loop": ["l"],
    "delete_clip": ["Delete", "Backspace"],
    "seek_back": ["ArrowLeft"],
    "seek_forward": ["ArrowRight"],
    "seek_back_big": ["Shift+ArrowLeft"],
    "seek_forward_big": ["Shift+ArrowRight"],
    "frame_back": [","],
    "frame_forward": ["."],
    "set_start": ["["],
    "set_end": ["]"],
    "prev_clip": ["ArrowUp"],
    "next_clip": ["ArrowDown"],
    "speed": ["s"],
    "zoom_in": ["=", "+"],
    "zoom_out": ["-"],
    "zoom_fit": ["f"],
    "undo": ["Ctrl+z", "Meta+z"],
    "deselect": ["Escape"],
}

ACTION_LABELS = {
    "play_pause": "Play / pause",
    "cut": "Cut — start / end a clip at the playhead",
    "loop": "Loop current segment",
    "delete_clip": "Delete selected clip",
    "seek_back": "Back 1 second",
    "seek_forward": "Forward 1 second",
    "seek_back_big": "Back 5 seconds",
    "seek_forward_big": "Forward 5 seconds",
    "frame_back": "Previous frame",
    "frame_forward": "Next frame",
    "set_start": "Set selected clip start to playhead",
    "set_end": "Set selected clip end to playhead",
    "prev_clip": "Select previous clip",
    "next_clip": "Select next clip",
    "speed": "Change playback speed",
    "zoom_in": "Zoom timeline in",
    "zoom_out": "Zoom timeline out",
    "zoom_fit": "Fit timeline",
    "undo": "Undo",
    "deselect": "Deselect clip",
}

# Shown in the employee portal's Shortcuts dialog (the admin settings page keeps the English list above).
ACTION_LABELS_BN = {
    "play_pause": "ভিডিও চালু / থামান",
    "cut": "কাট — প্লেহেডের জায়গায় ক্লিপ শুরু / শেষ",
    "loop": "বর্তমান অংশটা লুপে চালান",
    "delete_clip": "সিলেক্ট করা ক্লিপ মুছুন",
    "seek_back": "১ সেকেন্ড পেছনে",
    "seek_forward": "১ সেকেন্ড সামনে",
    "seek_back_big": "৫ সেকেন্ড পেছনে",
    "seek_forward_big": "৫ সেকেন্ড সামনে",
    "frame_back": "আগের ফ্রেম",
    "frame_forward": "পরের ফ্রেম",
    "set_start": "সিলেক্ট করা ক্লিপের শুরু প্লেহেডে আনুন",
    "set_end": "সিলেক্ট করা ক্লিপের শেষ প্লেহেডে আনুন",
    "prev_clip": "আগের ক্লিপ সিলেক্ট করুন",
    "next_clip": "পরের ক্লিপ সিলেক্ট করুন",
    "speed": "প্লেব্যাক স্পিড বদলান",
    "zoom_in": "টাইমলাইন জুম ইন",
    "zoom_out": "টাইমলাইন জুম আউট",
    "zoom_fit": "পুরো টাইমলাইন দেখান (Fit)",
    "undo": "Undo (আগের অবস্থায় ফেরা)",
    "deselect": "ক্লিপ সিলেকশন বাতিল",
}

CUT_MODES = {
    "toggle": "N starts a clip at the playhead, N again ends it (gaps allowed between clips)",
    "split": "N cuts at the playhead — each cut closes a clip that starts at the previous cut",
}

DEFAULTS = {
    "cut_mode": "toggle",
    "speeds": [1, 1.5, 2, 0.5, 0.75],
    "frame_rate": 30,
    "shortcuts": DEFAULT_SHORTCUTS,
}


def tool_config() -> dict:
    cfg = get_setting("practice_tool", DEFAULTS)
    shortcuts = {**DEFAULT_SHORTCUTS, **(cfg.get("shortcuts") or {})}
    return {**DEFAULTS, **cfg, "shortcuts": shortcuts}


def save_tool_config(cfg: dict) -> None:
    set_setting("practice_tool", cfg)
