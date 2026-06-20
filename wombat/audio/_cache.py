"""Shared helpers for audio-derived caches (waveforms, beat grids).

Both the waveform and beat-detection pipelines decode audio with ffmpeg and
cache their (slow-to-compute) results on disk keyed by source path + mtime.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def ffmpeg_path() -> str | None:
    """Path to the ffmpeg binary, or ``None`` if not on PATH."""
    return shutil.which("ffmpeg")


def cache_subdir(name: str) -> Path:
    """A named subdirectory under the app cache location (not created)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    return Path(base) / name


def cache_key(source_path: str) -> str:
    """Stable digest of a source file's path + mtime, for cache filenames."""
    try:
        mtime = int(Path(source_path).stat().st_mtime * 1000)
    except OSError:
        mtime = 0
    return hashlib.sha256(f"{source_path}:{mtime}".encode()).hexdigest()[:20]
