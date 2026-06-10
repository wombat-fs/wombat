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


def load() -> dict[str, str]:
    """Return merged bindings: defaults overridden by user file.

    Only keys that exist in DEFAULTS are honoured; extras are logged and
    dropped so typos don't silently accumulate.
    """
    bindings = dict(DEFAULTS)
    path = config_path()
    if not path.exists():
        return bindings
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(user, dict):
            log.warning("keybindings.json: expected a JSON object, ignoring")
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
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not load keybindings.json: %s", exc)
    return bindings


def load_action_keys() -> list[str]:
    """Return the 11-element action-key list, merged with user overrides.

    The list maps to ACTION_KEY_POSITIONS index-for-index:
    ``load_action_keys()[i]`` is the key that inserts an action at
    ``ACTION_KEY_POSITIONS[i]``.
    """
    keys = list(_ACTION_KEY_DEFAULTS)
    path = config_path()
    if not path.exists():
        return keys
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(user, dict) and "action_keys" in user:
            val = user["action_keys"]
            if isinstance(val, list) and len(val) == len(_ACTION_KEY_DEFAULTS):
                if all(isinstance(v, str) for v in val):
                    return list(val)
                else:
                    log.warning("keybindings.json: action_keys must be a list of strings")
            else:
                log.warning(
                    "keybindings.json: action_keys must have exactly %d entries",
                    len(_ACTION_KEY_DEFAULTS),
                )
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not load action_keys from keybindings.json: %s", exc)
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
