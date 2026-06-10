"""Waveform extraction and caching.

Uses ffmpeg to decode audio to raw PCM, then computes per-bucket average
absolute amplitude (same algorithm as OFS ``OFS_Waveform::LoadFlac``).
Results are cached as numpy binary files keyed by video path + mtime.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QStandardPaths

log = logging.getLogger(__name__)

# Audio decode parameters — low sample rate is plenty for waveform display.
_SAMPLE_RATE = 8000          # Hz for the decoded PCM
_PEAKS_PER_SEC = 100.0       # resolution of stored peak array (peaks/second)
_BUCKET_SIZE = int(_SAMPLE_RATE / _PEAKS_PER_SEC)   # samples per stored peak


@dataclass
class WaveformData:
    """Peak amplitude array, one float32 per 1/_PEAKS_PER_SEC second."""

    peaks: np.ndarray   # shape (N,), dtype float32, values 0..1
    duration: float     # total audio duration in seconds

    @property
    def rate(self) -> float:
        return _PEAKS_PER_SEC

    def samples_for_range(self, t0: float, t1: float, n_pixels: int) -> np.ndarray:
        """Return an array of `n_pixels` amplitude values for the time window [t0, t1].

        When zoomed out (many peaks per pixel) takes the max over each pixel's
        covered peaks — so transients are never missed.  When zoomed in
        (sub-peak resolution) uses nearest-neighbour.
        """
        if n_pixels <= 0 or len(self.peaks) == 0:
            return np.zeros(max(0, n_pixels), dtype=np.float32)

        i0 = max(0, int(t0 * self.rate))
        i1 = min(len(self.peaks), int(t1 * self.rate) + 1)

        if i0 >= i1:
            return np.zeros(n_pixels, dtype=np.float32)

        source = self.peaks[i0:i1]
        n_src = len(source)

        if n_src <= n_pixels:
            # Zoomed in — upsample with nearest-neighbour
            indices = np.linspace(0, n_src - 1, n_pixels).astype(np.intp)
            indices = np.clip(indices, 0, n_src - 1)
            return source[indices]
        else:
            # Zoomed out — max pooling so peaks are never lost
            # Map each output pixel to a contiguous slice of source
            edges = np.linspace(0, n_src, n_pixels + 1).astype(np.intp)
            out = np.empty(n_pixels, dtype=np.float32)
            for i in range(n_pixels):
                lo, hi = edges[i], edges[i + 1]
                out[i] = source[lo:hi].max() if lo < hi else 0.0
            return out


# ---------------------------------------------------------------------------
# Cache helpers

def _cache_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    return Path(base) / "waveforms"


def _cache_key(video_path: str) -> str:
    try:
        mtime = int(Path(video_path).stat().st_mtime * 1000)
    except OSError:
        mtime = 0
    digest = hashlib.sha256(f"{video_path}:{mtime}".encode()).hexdigest()[:20]
    return digest


def _load_cache(video_path: str) -> WaveformData | None:
    path = _cache_dir() / f"{_cache_key(video_path)}.npy"
    if not path.exists():
        return None
    try:
        arr = np.load(str(path))
        # First element = duration (float64 stored as float32 is lossy; keep first elem as f64)
        duration = float(arr[0])
        peaks = arr[1:].astype(np.float32)
        return WaveformData(peaks=peaks, duration=duration)
    except Exception as exc:
        log.debug("Waveform cache read failed: %s", exc)
        return None


def _save_cache(video_path: str, wf: WaveformData) -> None:
    path = _cache_dir() / f"{_cache_key(video_path)}.npy"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        arr = np.empty(1 + len(wf.peaks), dtype=np.float32)
        arr[0] = wf.duration
        arr[1:] = wf.peaks
        np.save(str(path), arr)
    except Exception as exc:
        log.debug("Waveform cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Extraction

def _ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def extract_waveform(video_path: str) -> WaveformData | None:
    """Decode audio and compute peak amplitudes.  Blocking; call from a thread.

    Returns ``None`` if ffmpeg is unavailable or the video has no audio.
    """
    cached = _load_cache(video_path)
    if cached is not None:
        log.debug("Waveform loaded from cache for: %s", video_path)
        return cached

    ffmpeg = _ffmpeg_path()
    if ffmpeg is None:
        log.warning("ffmpeg not found on PATH — audio waveform unavailable")
        return None

    log.debug("Extracting waveform: %s", video_path)
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-i", video_path,
                "-vn",                          # no video
                "-acodec", "pcm_s16le",
                "-ar", str(_SAMPLE_RATE),
                "-ac", "1",                     # mono
                "-f", "s16le",
                "pipe:1",                       # raw PCM to stdout
                "-loglevel", "quiet",
            ],
            capture_output=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("ffmpeg failed: %s", exc)
        return None

    if not proc.stdout:
        log.debug("No audio stream in: %s", video_path)
        return None

    # Decode s16le → float32 in [-1, 1]
    raw = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32)
    raw /= 32768.0
    duration = len(raw) / _SAMPLE_RATE

    # Compute average |amplitude| per bucket (OFS algorithm: avgSample / bucket_size)
    n_complete = len(raw) // _BUCKET_SIZE
    if n_complete == 0:
        return None
    chunks = raw[: n_complete * _BUCKET_SIZE].reshape(n_complete, _BUCKET_SIZE)
    peaks = np.abs(chunks).mean(axis=1).astype(np.float32)

    # Normalize to [0, 1] like OFS's MapRange step
    peak_max = peaks.max()
    if peak_max > 0.0:
        peaks /= peak_max

    wf = WaveformData(peaks=peaks, duration=duration)
    _save_cache(video_path, wf)
    log.debug("Waveform extracted: %.1f s, %d peaks", duration, len(peaks))
    return wf
