"""Position algorithms — generate pos values at a sequence of beat times.

Each class implements PosAlgorithm.positions(times, sample_base) -> np.ndarray.
`sample_base` is None or a callable that returns base signal values at given times.
All return float64 arrays (pre-clamp); BeatSnippet clamps to 0-100 and rounds.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from wombat.domain.snippets.base import ParamSpec, PosAlgorithm


class Alternate(PosAlgorithm):
    """Toggle between two values on successive beats."""

    def __init__(self, low: int = 0, high: int = 100) -> None:
        self.low = low
        self.high = high

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("high", "High", "int", 100, min=0, max=100, step=1),
            ParamSpec("low", "Low", "int", 0, min=0, max=100, step=1),
        ]

    def positions(self, times: np.ndarray,
                  sample_base: Callable[[np.ndarray], np.ndarray] | None) -> np.ndarray:
        n = len(times)
        result = np.empty(n, dtype=np.float64)
        for i in range(n):
            result[i] = float(self.high if i % 2 == 0 else self.low)
        return result


class Constant(PosAlgorithm):
    """Fixed position at every beat."""

    def __init__(self, value: int = 50) -> None:
        self.value = value

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("value", "Value", "int", 50, min=0, max=100, step=1),
        ]

    def positions(self, times: np.ndarray,
                  sample_base: Callable[[np.ndarray], np.ndarray] | None) -> np.ndarray:
        return np.full(len(times), float(self.value), dtype=np.float64)


class Ramp(PosAlgorithm):
    """Linear ramp from start to end across all beats."""

    def __init__(self, start: int = 0, end: int = 100) -> None:
        self.start = start
        self.end = end

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("start", "Start pos", "int", 0, min=0, max=100, step=1),
            ParamSpec("end", "End pos", "int", 100, min=0, max=100, step=1),
        ]

    def positions(self, times: np.ndarray,
                  sample_base: Callable[[np.ndarray], np.ndarray] | None) -> np.ndarray:
        n = len(times)
        if n == 0:
            return np.array([], dtype=np.float64)
        if n == 1:
            return np.array([float(self.start)], dtype=np.float64)
        return np.linspace(float(self.start), float(self.end), n)


class Random(PosAlgorithm):
    """Seeded uniform random positions (reproducible per seed)."""

    def __init__(self, low: int = 0, high: int = 100, seed: int = 42) -> None:
        self.low = low
        self.high = high
        self.seed = seed

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("low", "Low", "int", 0, min=0, max=100, step=1),
            ParamSpec("high", "High", "int", 100, min=0, max=100, step=1),
            ParamSpec("seed", "Seed", "int", 42, min=0, max=9999, step=1),
        ]

    def positions(self, times: np.ndarray,
                  sample_base: Callable[[np.ndarray], np.ndarray] | None) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        lo, hi = float(min(self.low, self.high)), float(max(self.low, self.high))
        return rng.uniform(lo, hi, len(times))


class _WaveformPos(PosAlgorithm):
    """Shared base for waveform-sampled-at-beat-times algorithms."""

    waveform: str = "sine"

    def __init__(self, amplitude: float = 50.0, frequency: float = 1.0,
                 center: int = 50, phase: float = 0.0) -> None:
        self.amplitude = amplitude
        self.frequency = frequency
        self.center = center
        self.phase = phase

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("amplitude", "Amplitude", "float", 50.0, min=0.0, max=50.0, step=1.0),
            ParamSpec("frequency", "Frequency (Hz)", "float", 1.0, min=0.01, max=20.0, step=0.1),
            ParamSpec("center", "Center", "int", 50, min=0, max=100, step=1),
            ParamSpec("phase", "Phase (°)", "float", 0.0, min=0.0, max=360.0, step=1.0),
        ]

    def _wave(self, arg: np.ndarray, t_rel: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def positions(self, times: np.ndarray,
                  sample_base: Callable[[np.ndarray], np.ndarray] | None) -> np.ndarray:
        if len(times) == 0:
            return np.array([], dtype=np.float64)
        phase_rad = math.radians(self.phase)
        t_rel = times - times[0]
        arg = 2.0 * math.pi * self.frequency * t_rel + phase_rad
        wave = self._wave(arg, t_rel)
        return self.center + wave * self.amplitude


class Sine(_WaveformPos):
    """Sine waveform sampled at beat times."""
    waveform = "sine"

    def _wave(self, arg: np.ndarray, t_rel: np.ndarray) -> np.ndarray:
        return np.sin(arg)


class Triangle(_WaveformPos):
    """Triangle waveform sampled at beat times."""
    waveform = "triangle"

    def _wave(self, arg: np.ndarray, t_rel: np.ndarray) -> np.ndarray:
        return (2.0 / math.pi) * np.arcsin(np.sin(arg))


class Square(_WaveformPos):
    """Square waveform sampled at beat times."""
    waveform = "square"

    def _wave(self, arg: np.ndarray, t_rel: np.ndarray) -> np.ndarray:
        return np.where(np.sin(arg) >= 0, 1.0, -1.0)


class Sawtooth(_WaveformPos):
    """Sawtooth waveform sampled at beat times."""
    waveform = "sawtooth"

    def _wave(self, arg: np.ndarray, t_rel: np.ndarray) -> np.ndarray:
        return 2.0 * ((self.frequency * t_rel + self.phase / 360.0) % 1.0) - 1.0


class AlternateOverBase(PosAlgorithm):
    """Alternating offset added to the underlying base signal at each beat.

    This is the README's "alternating values added to a base signal" — without
    needing a combined snippet; the primitives + stacking already cover it.
    """

    def __init__(self, low_offset: int = -30, high_offset: int = 30) -> None:
        self.low_offset = low_offset
        self.high_offset = high_offset

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("high_offset", "High offset", "int", 30, min=-100, max=100, step=1),
            ParamSpec("low_offset", "Low offset", "int", -30, min=-100, max=100, step=1),
        ]

    def positions(self, times: np.ndarray,
                  sample_base: Callable[[np.ndarray], np.ndarray] | None) -> np.ndarray:
        base_vals = sample_base(times) if sample_base is not None else np.full(len(times), 50.0)
        n = len(times)
        offsets = np.where(
            np.arange(n) % 2 == 0,
            float(self.high_offset),
            float(self.low_offset),
        )
        return base_vals + offsets


class FollowBase(PosAlgorithm):
    """Scale + offset derived from the underlying signal."""

    def __init__(self, scale: float = 1.0, offset: int = 0) -> None:
        self.scale = scale
        self.offset = offset

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("scale", "Scale", "float", 1.0, min=-3.0, max=3.0, step=0.1),
            ParamSpec("offset", "Offset", "int", 0, min=-100, max=100, step=1),
        ]

    def positions(self, times: np.ndarray,
                  sample_base: Callable[[np.ndarray], np.ndarray] | None) -> np.ndarray:
        base_vals = sample_base(times) if sample_base is not None else np.full(len(times), 50.0)
        return base_vals * self.scale + float(self.offset)
