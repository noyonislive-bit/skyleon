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
