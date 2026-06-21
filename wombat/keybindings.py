"""Keybinding configuration — defaults and JSON user-override loader.

The config file lives at the path returned by ``config_path()``.
Users edit it directly; unknown keys are ignored, missing keys fall back
to the defaults defined here.

Run ``write_template()`` once to create a pre-populated template that
the user can then customise.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QStandardPaths

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical action names → default key sequences (Qt key string format).
# Empty string means "no shortcut" — the action is reachable only via menus
# or toolbar.

DEFAULTS: dict[str, str] = {
    # --- File ---
    "new_project":       "Ctrl+N",
    "open_project":      "Ctrl+O",
    "open_media":        "Ctrl+Shift+O",
    "save":              "Ctrl+S",
    "save_as":           "Ctrl+Shift+S",
    "export":            "",
    "quit":              "Ctrl+Q",
    # --- Edit ---
    "undo":              "Ctrl+Z",
    "redo":              "Ctrl+Y",
    "cut":               "Ctrl+X",
    "copy":              "Ctrl+C",
    "paste":             "Ctrl+V",
    "select_all":        "Ctrl+A",
    "select_left":       "Ctrl+Alt+Left",
    "select_right":      "Ctrl+Alt+Right",
    "selection_start":   "",
    "selection_end":     "",
    "isolate_action":    "",
    "select_top":        "",
    "select_mid":        "",
    "select_bottom":     "",
    "invert_actions":    "",
    "equalize_actions":  "",
    "simplify_actions":  "",
    "delete":            "Delete",
    # --- Playback ---
    "play_pause":        "Space",
    "frame_forward":     "Right",
    "frame_back":        "Left",
    "seek_forward":      "Ctrl+Right",
    "seek_back":         "Ctrl+Left",
}

_COMMENTS: dict[str, str] = {
    "new_project":   "File: new project",
    "open_project":  "File: open project",
    "open_media":    "File: open media file",
    "save":          "File: save project",
    "save_as":       "File: save project as…",
    "export":        "File: export funscripts (no default)",
    "quit":          "File: quit",
    "undo":          "Edit: undo",
    "redo":          "Edit: redo",
    "cut":           "Edit: cut selection",
    "copy":          "Edit: copy selection",
    "paste":         "Edit: paste at playhead",
    "select_all":    "Edit: select all actions",
    "select_left":   "Edit: select actions left of playhead",
    "select_right":  "Edit: select actions right of playhead",
    "selection_start": "Edit: mark range start at playhead (no default)",
    "selection_end": "Edit: select range from mark to playhead (no default)",
    "isolate_action": "Edit: remove neighbours of action at playhead (no default)",
    "select_top":    "Edit: select only the top (peak) points (no default)",
    "select_mid":    "Edit: select only the mid points (no default)",
    "select_bottom": "Edit: select only the bottom (valley) points (no default)",
    "invert_actions": "Edit: invert selected positions (no default)",
    "equalize_actions": "Edit: equalize selected timing (no default)",
    "simplify_actions": "Edit: simplify (RDP) selection (no default)",
    "delete":        "Edit: delete selection",
    "play_pause":    "Playback: play / pause",
    "frame_forward": "Playback: step forward one frame",
    "frame_back":    "Playback: step back one frame",
    "seek_forward":  "Playback: seek forward 5 s",
    "seek_back":     "Playback: seek back 5 s",
}

# Action-insertion keys: each entry maps a key sequence to a position (0–100).
# Index 0 → pos 0, index 1 → pos 10, …, index 10 → pos 100.
# The default for pos 0 is backtick (key left of 1 on US/UK layouts); change
# this to match your keyboard layout if needed.
ACTION_KEY_POSITIONS: list[int] = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
_ACTION_KEY_DEFAULTS: list[str] = ["`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]

_SEEK_STEP = 5.0   # seconds for seek_forward / seek_back


# ---------------------------------------------------------------------------

def config_path() -> Path:
    """Platform-appropriate path for keybindings.json."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    return Path(base) / "keybindings.json"


def _strip_line_comments(text: str) -> str:
    """Remove ``//`` line comments, ignoring ``//`` that appear inside strings.

    write_template() emits a commented JSONC file for readability, but json
    itself is strict — so we strip comments before parsing.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":   # skip to end of line
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _read_user_config() -> dict | None:
    """Read, comment-strip, and parse the user config file.

    Returns the parsed dict, or None if the file is missing, unreadable,
    malformed, or not a JSON object.
    """
    path = config_path()
    if not path.exists():
        return None
    try:
        user = json.loads(_strip_line_comments(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not load keybindings.json: %s", exc)
        return None
    if not isinstance(user, dict):
        log.warning("keybindings.json: expected a JSON object, ignoring")
        return None
    return user


def load() -> dict[str, str]:
    """Return merged bindings: defaults overridden by user file.

    Only keys that exist in DEFAULTS are honoured; extras are logged and
    dropped so typos don't silently accumulate.
    """
    bindings = dict(DEFAULTS)
    user = _read_user_config()
    if user is None:
        return bindings
    for key, val in user.items():
        if key == "action_keys":
            continue  # handled by load_action_keys()
        if key not in DEFAULTS:
            log.debug("keybindings.json: unknown action %r, ignored", key)
            continue
        if not isinstance(val, str):
            log.warning("keybindings.json: value for %r must be a string", key)
            continue
        bindings[key] = val
    return bindings


def load_action_keys() -> list[str]:
    """Return the 11-element action-key list, merged with user overrides.

    The list maps to ACTION_KEY_POSITIONS index-for-index:
    ``load_action_keys()[i]`` is the key that inserts an action at
    ``ACTION_KEY_POSITIONS[i]``.
    """
    keys = list(_ACTION_KEY_DEFAULTS)
    user = _read_user_config()
    if user is None or "action_keys" not in user:
        return keys
    val = user["action_keys"]
    if isinstance(val, list) and len(val) == len(_ACTION_KEY_DEFAULTS):
        if all(isinstance(v, str) for v in val):
            return list(val)
        log.warning("keybindings.json: action_keys must be a list of strings")
    else:
        log.warning(
            "keybindings.json: action_keys must have exactly %d entries",
            len(_ACTION_KEY_DEFAULTS),
        )
    return keys


def write_template() -> None:
    """Write a commented template file if none exists yet."""
    path = config_path()
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["{"]
    items = list(DEFAULTS.items())
    for key, val in items:
        comment = _COMMENTS.get(key, "")
        lines.append(f'  "{key}": "{val}",  // {comment}')
    # action_keys array
    ak = json.dumps(_ACTION_KEY_DEFAULTS)
    lines.append(f'  "action_keys": {ak}  // insert action at pos 0,10,20,...,90,100')
    lines.append("}")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote default keybindings template: %s", path)
