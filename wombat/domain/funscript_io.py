"""Funscript file I/O — load/save with ms↔seconds conversion.

Unknown top-level and metadata keys are preserved so third-party tools'
injected data survives a round-trip (an OFS-flagged missing feature).
"""
from __future__ import annotations

import json
from pathlib import Path

from wombat.domain.action import Action, ActionList
from wombat.domain.funscript import Funscript, FunscriptMetadata

_METADATA_KNOWN_KEYS = {
    "type", "title", "creator", "scriptUrl", "videoUrl",
    "tags", "performers", "description", "license", "notes", "duration",
}

_TOP_KNOWN_KEYS = {"version", "inverted", "range", "metadata", "actions"}


class FunscriptError(Exception):
    """Raised for malformed or unreadable funscript files."""


def load_funscript(path: str | Path) -> Funscript:
    """Parse a .funscript JSON file and return a Funscript.

    - at_ms → at = at_ms / 1000.0 (float seconds)
    - pos clamped to 0–100
    - Actions sorted; duplicate timestamps: last one wins
    - Unknown top-level and metadata keys are stored in .extra
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise FunscriptError(f"Cannot read {path}: {e}") from e

    try:
        data: dict = json.loads(text)
    except json.JSONDecodeError as e:
        raise FunscriptError(f"Invalid JSON in {path}: {e}") from e

    if not isinstance(data, dict):
        raise FunscriptError(f"Expected JSON object at top level in {path}")
    if "actions" not in data:
        raise FunscriptError(f"Missing 'actions' key in {path}")

    # --- actions ---
    raw_actions = data["actions"]
    if not isinstance(raw_actions, list):
        raise FunscriptError(f"'actions' must be a list in {path}")

    # Build as dict keyed by at_ms to handle duplicates (last wins)
    seen: dict[float, int] = {}
    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        try:
            at_ms = int(item["at"])
            pos = max(0, min(100, int(item["pos"])))
        except (KeyError, TypeError, ValueError):
            continue
        seen[at_ms / 1000.0] = pos

    al = ActionList(Action(at, pos) for at, pos in seen.items())

    # --- metadata ---
    meta_data = data.get("metadata") or {}
    meta_extra = {k: v for k, v in meta_data.items() if k not in _METADATA_KNOWN_KEYS}
    metadata = FunscriptMetadata(
        type=str(meta_data.get("type", "basic")),
        title=str(meta_data.get("title", "")),
        creator=str(meta_data.get("creator", "")),
        script_url=str(meta_data.get("scriptUrl", "")),
        video_url=str(meta_data.get("videoUrl", "")),
        tags=list(meta_data.get("tags") or []),
        performers=list(meta_data.get("performers") or []),
        description=str(meta_data.get("description", "")),
        license=str(meta_data.get("license", "")),
        notes=str(meta_data.get("notes", "")),
        duration=int(meta_data.get("duration") or 0),
        extra=meta_extra,
    )

    # --- top-level extras ---
    top_extra = {k: v for k, v in data.items() if k not in _TOP_KNOWN_KEYS}

    return Funscript(
        actions=al,
        metadata=metadata,
        version=str(data.get("version", "1.0")),
        inverted=bool(data.get("inverted", False)),
        range_=int(data.get("range", 100)),
        extra=top_extra,
    )


def save_funscript(path: str | Path, fs: Funscript) -> None:
    """Write a Funscript to a .funscript JSON file.

    at (seconds) → round(at * 1000) as int ms.
    Known keys written first, then extra keys for both top-level and metadata.
    """
    meta = fs.metadata
    meta_obj: dict = {
        "type": meta.type,
        "title": meta.title,
        "creator": meta.creator,
        "scriptUrl": meta.script_url,
        "videoUrl": meta.video_url,
        "tags": meta.tags,
        "performers": meta.performers,
        "description": meta.description,
        "license": meta.license,
        "notes": meta.notes,
        "duration": meta.duration,
    }
    meta_obj.update(meta.extra)

    actions_list = [
        {"pos": a.pos, "at": round(a.at * 1000)}
        for a in fs.actions
    ]

    out: dict = {
        "version": fs.version,
        "inverted": fs.inverted,
        "range": fs.range_,
        "metadata": meta_obj,
        "actions": actions_list,
    }
    out.update(fs.extra)

    Path(path).write_text(json.dumps(out, indent=2), encoding="utf-8")
