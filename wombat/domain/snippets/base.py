"""Core abstractions for the snippet library.

ParamSpec — declares one tunable parameter (kind, range, default).
Rhythm    — generates beat timestamps over a span.
PosAlgorithm — generates positions at those timestamps.
BeatSnippet  — composes Rhythm × PosAlgorithm.
WaveformSnippet — dense-samples a continuous waveform over a span.

No Qt, no mpv imports here.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from wombat.domain.action import Action, ActionList


@dataclass
class ParamSpec:
    key: str
    label: str
    kind: Literal["int", "float", "bool", "choice"]
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[str] | None = None


# ------------------------------------------------------------------ protocols (structural typing)
# Concrete classes implement these implicitly — no inheritance required.


class Rhythm:
    """Base class / protocol for beat-timing generators."""

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return []

    def beats(self, span: tuple[float, float], fps: float | None) -> np.ndarray:
        """Return array of beat timestamps (seconds) within span."""
        raise NotImplementedError


class PosAlgorithm:
    """Base class / protocol for position generators."""

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return []

    def positions(
        self,
        times: np.ndarray,
        sample_base: Callable[[np.ndarray], np.ndarray] | None,
    ) -> np.ndarray:
        """Return float64 array of positions (pre-clamp) for each time in times."""
        raise NotImplementedError


# ------------------------------------------------------------------ helpers

def _snap_times(times: np.ndarray, fps: float) -> np.ndarray:
    frame_time = 1.0 / fps
    return np.round(times / frame_time) * frame_time


def _build_action_list(times: np.ndarray, positions: np.ndarray,
                       span: tuple[float, float]) -> ActionList:
    """Clamp, round, filter to span, build ActionList."""
    clamped = np.clip(np.round(positions), 0, 100).astype(np.int32)
    al = ActionList()
    start, end = span
    for t, p in zip(times, clamped):
        t_f = float(t)
        if start <= t_f <= end:
            al.add(Action(t_f, int(p)))
    return al


# ------------------------------------------------------------------ BeatSnippet

@dataclass
class BeatSnippet:
    """Composes a Rhythm × PosAlgorithm into a Snippet."""
    rhythm: Rhythm
    pos: PosAlgorithm
    name: str = "beat"

    def generate(
        self,
        span: tuple[float, float],
        *,
        base: ActionList | None = None,
        fps: float | None = None,
        snap_to_frame: bool = False,
    ) -> ActionList:
        times = self.rhythm.beats(span, fps)
        if len(times) == 0:
            return ActionList()

        if snap_to_frame and fps is not None and fps > 0:
            times = _snap_times(times, fps)

        sampler: Callable[[np.ndarray], np.ndarray] | None = None
        if base is not None:
            from wombat.domain.interpolate import values_at
            sampler = lambda ts: values_at(base, ts)  # noqa: E731

        raw = self.pos.positions(times, sampler)
        return _build_action_list(times, raw, span)

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return []


# ------------------------------------------------------------------ WaveformSnippet

@dataclass
class WaveformSnippet:
    """Dense-samples a continuous waveform over a span."""
    waveform: Literal["sine", "triangle", "square", "sawtooth"] = "sine"
    frequency: float = 1.0       # Hz
    amplitude: float = 50.0      # pos units from center
    center: int = 50             # baseline position 0-100
    phase: float = 0.0           # degrees
    duty_cycle: float = 0.5      # square wave only: fraction of period at +1 (0-1)
    resolution_hz: float = 60.0  # samples per second
    name: str = "waveform"

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("waveform", "Waveform", "choice", "sine",
                      choices=["sine", "triangle", "square", "sawtooth"]),
            ParamSpec("frequency", "Frequency (Hz)", "float", 1.0, min=0.01, max=20.0, step=0.1),
            ParamSpec("amplitude", "Amplitude", "float", 50.0, min=0.0, max=50.0, step=1.0),
            ParamSpec("center", "Center", "int", 50, min=0, max=100, step=1),
            ParamSpec("phase", "Phase (°)", "float", 0.0, min=0.0, max=360.0, step=1.0),
            ParamSpec("duty_cycle", "Duty Cycle", "float", 0.5, min=0.01, max=0.99, step=0.05),
            ParamSpec("resolution_hz", "Resolution (Hz)", "float", 60.0,
                      min=10.0, max=500.0, step=10.0),
        ]

    def generate(
        self,
        span: tuple[float, float],
        *,
        base: ActionList | None = None,
        fps: float | None = None,
        snap_to_frame: bool = False,
    ) -> ActionList:
        start, end = span
        duration = end - start
        if duration <= 0:
            return ActionList()

        if snap_to_frame and fps is not None and fps > 0:
            n = max(2, int(duration * fps) + 1)
            times = np.arange(n) / fps + start
            times = times[times <= end + 1e-9]
        else:
            n = max(2, int(math.ceil(duration * self.resolution_hz)))
            times = np.linspace(start, end, n)

        t_rel = times - start

        if self.waveform == "sine":
            phase_rad = math.radians(self.phase)
            arg = 2.0 * math.pi * self.frequency * t_rel + phase_rad
            wave = np.sin(arg)
        elif self.waveform == "triangle":
            phase_rad = math.radians(self.phase)
            arg = 2.0 * math.pi * self.frequency * t_rel + phase_rad
            wave = (2.0 / math.pi) * np.arcsin(np.sin(arg))
        elif self.waveform == "square":
            # duty_cycle: fraction of period at +1; starts at phase/360 offset
            phase_cycle = (self.phase / 360.0) % 1.0
            pos_in_cycle = (self.frequency * t_rel + phase_cycle) % 1.0
            dc = max(0.01, min(0.99, self.duty_cycle))
            wave = np.where(pos_in_cycle < dc, 1.0, -1.0)
        else:  # sawtooth — rises from -1 to +1 over each cycle
            phase_cycle = (self.phase / 360.0) % 1.0
            wave = 2.0 * ((self.frequency * t_rel + phase_cycle) % 1.0) - 1.0

        positions = self.center + wave * self.amplitude
        return _build_action_list(times, positions, span)
