"""Beat grids — detected musical beats/downbeats and the ``.beats`` format.

A ``BeatGrid`` is the in-memory model shared by audio beat detection, the
timeline overlay, snap-to-beat, and the snippet rhythm system.  The ``.beats``
file format (tab-separated ``time<TAB>count``, time in seconds, count 1 = downbeat)
is its serialization, so import/export and detection feed the same path.

This module is headless and dependency-light (numpy only).  The detection
service that runs the external ``beat_this_cpp`` binary lives separately so this
stays trivially testable.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from wombat.audio._cache import cache_key, cache_subdir, ffmpeg_path

log = logging.getLogger(__name__)

# count value meaning "position within bar unknown" (single-column .beats input)
UNKNOWN_COUNT = 0
DOWNBEAT_COUNT = 1

# upper bound for one detection run; transformer inference on long audio is slow
_DETECT_TIMEOUT_S = 600


@dataclass(frozen=True)
class BeatGrid:
    """Sorted beat timestamps with per-beat bar position.

    ``times`` are seconds (float64), strictly the order they should display in.
    ``counts`` parallels ``times``: 1 = downbeat, 2..N = other beats within the
    bar, 0 = unknown.  Construct via the class so invariants (matching lengths,
    sorted, correct dtypes) hold; helpers below preserve them.
    """

    times: np.ndarray   # float64 seconds, sorted ascending
    counts: np.ndarray  # int32, 1 = downbeat, 2..N = beat-in-bar, 0 = unknown

    def __post_init__(self) -> None:
        times = np.asarray(self.times, dtype=np.float64).reshape(-1)
        counts = np.asarray(self.counts, dtype=np.int32).reshape(-1)
        if len(times) != len(counts):
            raise ValueError(
                f"times/counts length mismatch: {len(times)} != {len(counts)}"
            )
        if len(times) > 1 and np.any(np.diff(times) < 0):
            order = np.argsort(times, kind="stable")
            times = times[order]
            counts = counts[order]
        # frozen dataclass: bypass the immutability guard to store normalized arrays
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "counts", counts)

    @classmethod
    def empty(cls) -> BeatGrid:
        return cls(np.empty(0, dtype=np.float64), np.empty(0, dtype=np.int32))

    def __len__(self) -> int:
        return len(self.times)

    @property
    def downbeats(self) -> np.ndarray:
        """Timestamps where count == 1 (bar starts)."""
        return self.times[self.counts == DOWNBEAT_COUNT]

    def in_span(self, t0: float, t1: float) -> BeatGrid:
        """Sub-grid of beats with ``t0 <= time <= t1`` (order preserved)."""
        if len(self.times) == 0:
            return self
        lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
        mask = (self.times >= lo) & (self.times <= hi)
        return BeatGrid(self.times[mask], self.counts[mask])

    def nearest(self, t: float) -> float | None:
        """Timestamp of the beat closest to ``t``, or ``None`` if empty."""
        if len(self.times) == 0:
            return None
        i = int(np.searchsorted(self.times, t))
        # candidates straddling t: index i-1 and i (clamped)
        best: float | None = None
        best_d = float("inf")
        for j in (i - 1, i):
            if 0 <= j < len(self.times):
                d = abs(float(self.times[j]) - t)
                if d < best_d:
                    best_d = d
                    best = float(self.times[j])
        return best


def parse_beats(text: str) -> BeatGrid:
    """Parse ``.beats`` text into a ``BeatGrid``.

    Each non-blank line is ``time`` optionally followed by whitespace and a
    ``count``.  Whitespace-separated so both tab- and space-delimited files work.
    Lines without a parseable leading float are skipped (e.g. comments/headers).
    A missing or non-integer count becomes ``UNKNOWN_COUNT``.
    """
    times: list[float] = []
    counts: list[int] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        try:
            t = float(parts[0])
        except ValueError:
            continue
        count = UNKNOWN_COUNT
        if len(parts) > 1:
            try:
                count = int(float(parts[1]))
            except ValueError:
                count = UNKNOWN_COUNT
        times.append(t)
        counts.append(count)
    return BeatGrid(
        np.asarray(times, dtype=np.float64),
        np.asarray(counts, dtype=np.int32),
    )


def serialize_beats(grid: BeatGrid) -> str:
    """Serialize a ``BeatGrid`` to ``.beats`` text (tab-separated, trailing newline).

    Times are written with millisecond precision; ``UNKNOWN_COUNT`` beats are
    written as a single column so the file round-trips through ``parse_beats``.
    """
    lines: list[str] = []
    for t, c in zip(grid.times, grid.counts):
        if int(c) == UNKNOWN_COUNT:
            lines.append(f"{float(t):.3f}")
        else:
            lines.append(f"{float(t):.3f}\t{int(c)}")
    return "\n".join(lines) + ("\n" if lines else "")


# --------------------------------------------------------------------- tool resolution

def _get_settings():
    """Return AppSettings, or ``None`` if Qt settings are unavailable.

    Indirected so tests can bypass the user's stored preferences.
    """
    try:
        from wombat.settings import AppSettings
        return AppSettings()
    except Exception:   # pragma: no cover - defensive
        return None


def _model_beside(binary: str | None) -> str | None:
    """Best-effort search for ``beat_this.onnx`` near the binary."""
    if not binary:
        return None
    bdir = Path(binary).resolve().parent
    candidates = [
        bdir / "beat_this.onnx",
        bdir / "onnx" / "beat_this.onnx",
        bdir.parent / "onnx" / "beat_this.onnx",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def resolve_beat_tool(
    binary: str | None = None, model: str | None = None
) -> tuple[str | None, str | None]:
    """Locate the beat_this_cpp binary and ONNX model.

    Resolution order for each, first non-empty wins: explicit argument →
    stored preference → environment variable → ``shutil.which`` (binary) /
    model found beside the binary.  Returns ``(binary, model)`` with ``None``
    for anything that could not be resolved.
    """
    settings = _get_settings() if (binary is None or model is None) else None

    if not binary:
        binary = (settings.load_beat_binary_path() if settings else "") \
            or os.environ.get("WOMBAT_BEAT_THIS_BIN") \
            or shutil.which("beat_this_cpp")
    if not model:
        model = (settings.load_beat_model_path() if settings else "") \
            or os.environ.get("WOMBAT_BEAT_THIS_MODEL") \
            or _model_beside(binary)

    return (binary or None, model or None)


# --------------------------------------------------------------------- disk cache

def _cache_dir() -> Path:
    return cache_subdir("beats")


def _load_cache(video_path: str) -> BeatGrid | None:
    path = _cache_dir() / f"{cache_key(video_path)}.npz"
    if not path.exists():
        return None
    try:
        data = np.load(path)
        return BeatGrid(data["times"], data["counts"])
    except Exception as exc:
        log.debug("Beat cache read failed: %s", exc)
        return None


def _save_cache(video_path: str, grid: BeatGrid) -> None:
    path = _cache_dir() / f"{cache_key(video_path)}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        np.savez(path, times=grid.times, counts=grid.counts)
    except Exception as exc:
        log.debug("Beat cache write failed: %s", exc)


# --------------------------------------------------------------------- detection

def _extract_audio(ffmpeg: str, video_path: str, out_wav: Path) -> bool:
    """Decode the source audio to a mono WAV (the model resamples internally)."""
    try:
        subprocess.run(
            [
                ffmpeg,
                "-i", video_path,
                "-vn",            # no video
                "-ac", "1",       # mono
                "-y",             # overwrite
                str(out_wav),
                "-loglevel", "quiet",
            ],
            capture_output=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("ffmpeg audio extraction failed: %s", exc)
        return False
    return out_wav.exists() and out_wav.stat().st_size > 0


def detect_beats(
    video_path: str,
    *,
    binary: str | None = None,
    model: str | None = None,
    use_cache: bool = True,
) -> BeatGrid | None:
    """Detect beats in a video's audio via the external ``beat_this_cpp`` binary.

    Blocking; call from a background thread.  Returns ``None`` (with a log
    message, never raising) if the tool or ffmpeg is unavailable, the audio
    can't be decoded, or detection fails — callers degrade gracefully.
    Results are cached on disk keyed by source path + mtime.
    """
    if use_cache:
        cached = _load_cache(video_path)
        if cached is not None:
            log.debug("Beats loaded from cache for: %s", video_path)
            return cached

    binary, model = resolve_beat_tool(binary, model)
    if not binary or not model:
        log.warning("beat_this_cpp binary/model not configured — beat detection unavailable")
        return None

    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        log.warning("ffmpeg not found on PATH — beat detection unavailable")
        return None

    log.debug("Detecting beats: %s", video_path)
    with tempfile.TemporaryDirectory(prefix="wombat-beats-") as td:
        wav = Path(td) / "audio.wav"
        beats_file = Path(td) / "out.beats"
        if not _extract_audio(ffmpeg, video_path, wav):
            return None
        try:
            proc = subprocess.run(
                [binary, model, str(wav), "--output-beats", str(beats_file)],
                capture_output=True,
                timeout=_DETECT_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("beat_this_cpp invocation failed: %s", exc)
            return None
        if proc.returncode != 0:
            log.warning(
                "beat_this_cpp exited %d: %s",
                proc.returncode,
                proc.stderr.decode("utf-8", "replace").strip()[:500],
            )
            return None
        if not beats_file.exists():
            log.warning("beat_this_cpp produced no .beats output")
            return None
        grid = parse_beats(beats_file.read_text())

    if use_cache:
        _save_cache(video_path, grid)
    log.debug("Detected %d beats for: %s", len(grid), video_path)
    return grid
