"""Rhythm generators — produce beat timestamps over a span.

Each class implements Rhythm.beats(span, fps) -> np.ndarray of times.
All classes expose param_specs() so the UI can auto-generate controls.
"""
from __future__ import annotations

import math

import numpy as np

from wombat.domain.snippets.base import ParamSpec, Rhythm


class ConstantBeat(Rhythm):
    """Evenly spaced beats at a fixed BPM."""

    def __init__(self, bpm: float = 120.0, offset: float = 0.0) -> None:
        self.bpm = bpm
        self.offset = offset  # seconds from span start to first beat

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("bpm", "BPM", "float", 120.0, min=10.0, max=600.0, step=1.0),
            ParamSpec("offset", "Offset (s)", "float", 0.0, min=0.0, max=10.0, step=0.01),
        ]

    def beats(self, span: tuple[float, float], fps: float | None) -> np.ndarray:
        start, end = span
        interval = 60.0 / max(self.bpm, 0.01)
        t0 = start + self.offset
        if t0 < start:
            t0 = start
        # advance t0 to be >= start if offset caused undershoot
        if t0 > end:
            return np.array([], dtype=np.float64)
        n = max(0, int((end - t0) / interval) + 1)
        times = t0 + np.arange(n) * interval
        return times[times <= end + 1e-9]


class Subdivided(Rhythm):
    """BPM with N equal subdivisions per beat."""

    def __init__(self, bpm: float = 120.0, subdivisions: int = 4) -> None:
        self.bpm = bpm
        self.subdivisions = subdivisions

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("bpm", "BPM", "float", 120.0, min=10.0, max=600.0, step=1.0),
            ParamSpec("subdivisions", "Subdivisions", "int", 4, min=1, max=16, step=1),
        ]

    def beats(self, span: tuple[float, float], fps: float | None) -> np.ndarray:
        start, end = span
        interval = 60.0 / (max(self.bpm, 0.01) * max(self.subdivisions, 1))
        n = max(0, int((end - start) / interval) + 1)
        times = start + np.arange(n) * interval
        return times[times <= end + 1e-9]


class Swing(Rhythm):
    """Alternating long/short beat spacing (swing feel).

    swing_ratio=0.5 → straight (equal spacing).
    swing_ratio=0.67 → typical jazz swing (2:1 long:short).
    """

    def __init__(self, bpm: float = 120.0, swing_ratio: float = 0.67) -> None:
        self.bpm = bpm
        self.swing_ratio = swing_ratio

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("bpm", "BPM", "float", 120.0, min=10.0, max=600.0, step=1.0),
            ParamSpec("swing_ratio", "Swing ratio", "float", 0.67, min=0.5, max=0.95, step=0.01),
        ]

    def beats(self, span: tuple[float, float], fps: float | None) -> np.ndarray:
        start, end = span
        ratio = max(0.5, min(0.99, self.swing_ratio))
        base_interval = 60.0 / max(self.bpm, 0.01)
        # two subdivisions per beat: long + short = 2 * base_interval
        long_gap = 2.0 * base_interval * ratio
        short_gap = 2.0 * base_interval - long_gap

        times: list[float] = [start]
        t = start
        toggle = True
        while True:
            gap = long_gap if toggle else short_gap
            t += gap
            if t > end + 1e-9:
                break
            times.append(t)
            toggle = not toggle
        return np.array(times, dtype=np.float64)


def _euclidean_pattern(pulses: int, steps: int) -> list[bool]:
    """Bresenham-style Euclidean (Bjorklund) rhythm pattern."""
    if steps <= 0:
        return []
    pulses = max(0, min(pulses, steps))
    if pulses == 0:
        return [False] * steps
    if pulses == steps:
        return [True] * steps
    pattern: list[bool] = []
    bucket = 0
    for _ in range(steps):
        bucket += pulses
        if bucket >= steps:
            bucket -= steps
            pattern.append(True)
        else:
            pattern.append(False)
    return pattern


class Euclidean(Rhythm):
    """Euclidean (Bjorklund) rhythm: `pulses` spread evenly across `steps` at BPM."""

    def __init__(self, pulses: int = 3, steps: int = 8, bpm: float = 120.0) -> None:
        self.pulses = pulses
        self.steps = steps
        self.bpm = bpm

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("pulses", "Pulses", "int", 3, min=1, max=32, step=1),
            ParamSpec("steps", "Steps", "int", 8, min=1, max=32, step=1),
            ParamSpec("bpm", "BPM", "float", 120.0, min=10.0, max=600.0, step=1.0),
        ]

    def beats(self, span: tuple[float, float], fps: float | None) -> np.ndarray:
        start, end = span
        n_steps = max(1, self.steps)
        step_dur = 60.0 / (max(self.bpm, 0.01) * n_steps / n_steps)
        # step_dur = duration of one step = beat_duration / n_steps... wait:
        # At BPM, one beat = 60/BPM seconds. Each "step" is 1/n_steps of a beat.
        # Actually the Euclidean rhythm operates over n_steps at BPM, so:
        # one full pattern = n_steps steps, one step = 60/bpm/n_steps? No.
        # Typical interpretation: one pattern cycle = n_steps beats at BPM.
        step_dur = 60.0 / max(self.bpm, 0.01)  # one step = one beat at BPM
        pattern = _euclidean_pattern(max(1, self.pulses), n_steps)
        cycle_dur = step_dur * n_steps

        times: list[float] = []
        cycle_offset = 0.0
        while start + cycle_offset <= end + 1e-9:
            for i, hit in enumerate(pattern):
                t = start + cycle_offset + i * step_dur
                if hit and t <= end + 1e-9:
                    times.append(t)
            cycle_offset += cycle_dur
        return np.array(times, dtype=np.float64)


class DetectedBeats(Rhythm):
    """Beats from audio analysis of the loaded video.

    Unlike the other rhythms, the timing comes from a runtime ``BeatGrid``
    rather than parameters.  The grid is injected by the snippet panel at build
    time (it is session state, not something serialized into the project), so a
    freshly constructed instance with no grid simply yields no beats.
    """

    def __init__(self, downbeats_only: bool = False, grid=None) -> None:
        self.downbeats_only = downbeats_only
        self.grid = grid   # BeatGrid | None

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("downbeats_only", "Downbeats only", "bool", False),
        ]

    def beats(self, span: tuple[float, float], fps: float | None) -> np.ndarray:
        if self.grid is None or len(self.grid) == 0:
            return np.array([], dtype=np.float64)
        sub = self.grid.in_span(span[0], span[1])
        times = sub.downbeats if self.downbeats_only else sub.times
        return np.asarray(times, dtype=np.float64)


class Accelerando(Rhythm):
    """Tempo glide from bpm_start to bpm_end across the span."""

    def __init__(self, bpm_start: float = 60.0, bpm_end: float = 180.0) -> None:
        self.bpm_start = bpm_start
        self.bpm_end = bpm_end

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("bpm_start", "Start BPM", "float", 60.0, min=10.0, max=600.0, step=1.0),
            ParamSpec("bpm_end", "End BPM", "float", 180.0, min=10.0, max=600.0, step=1.0),
        ]

    def beats(self, span: tuple[float, float], fps: float | None) -> np.ndarray:
        start, end = span
        duration = end - start
        if duration <= 0:
            return np.array([start], dtype=np.float64)

        times: list[float] = [start]
        t_rel = 0.0  # seconds elapsed within span
        while True:
            f = min(t_rel / duration, 1.0)
            bpm = self.bpm_start + f * (self.bpm_end - self.bpm_start)
            interval = 60.0 / max(bpm, 0.01)
            t_rel += interval
            if start + t_rel > end + 1e-9:
                break
            times.append(start + t_rel)
        return np.array(times, dtype=np.float64)
