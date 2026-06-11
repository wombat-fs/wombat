"""Multi-axis filename convention for funscript channels.

Convention: base.<channel>.funscript
  "clip.alpha.funscript"  ← channel "alpha"
  "clip.funscript"        ← main channel (no suffix, name in MAIN_CHANNEL_NAMES)
"""
from __future__ import annotations

from pathlib import Path

MAIN_CHANNEL_NAMES: frozenset[str] = frozenset({"orig", "main", "script", ""})


def channel_filename(base: str, channel_name: str) -> str:
    """Return the .funscript filename for a given channel of a media base stem."""
    if channel_name in MAIN_CHANNEL_NAMES:
        return f"{base}.funscript"
    return f"{base}.{channel_name}.funscript"


def parse_channel_name(filename: str, base: str) -> str | None:
    """Return channel name for a funscript filename, or None if not a sibling of base.

    Returns "" for the main (no-suffix) channel.
    """
    if filename == f"{base}.funscript":
        return ""
    prefix = f"{base}."
    suffix = ".funscript"
    if filename.startswith(prefix) and filename.endswith(suffix):
        middle = filename[len(prefix) : -len(suffix)]
        if middle and "." not in middle:
            return middle
    return None


def discover_siblings(media_path: str) -> list[tuple[str, str]]:
    """Scan the media directory for base.funscript and base.*.funscript.

    Returns [(channel_name, abs_path), ...] sorted by filename.
    channel_name is "" for the main channel.
    """
    p = Path(media_path)
    base = p.stem
    directory = p.parent
    results: list[tuple[str, str]] = []
    for f in sorted(directory.iterdir()):
        if not f.is_file():
            continue
        name = parse_channel_name(f.name, base)
        if name is not None:
            results.append((name, str(f)))
    # Main channel (empty name → "orig") first, rest alphabetical by channel name
    results.sort(key=lambda t: ("" if t[0] == "" else t[0]))
    return results
