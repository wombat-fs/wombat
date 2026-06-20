"""Named preset registry.

Each entry bundles a configured Snippet (BeatSnippet or WaveformSnippet) with
a friendly name and category.  The panel enumerates these and also lets users
build from scratch by choosing rhythm + pos algorithm directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from wombat.domain.snippets.base import BeatSnippet, WaveformSnippet
from wombat.domain.snippets.positions import (
    Alternate,
    AlternateOverBase,
    Constant,
    FollowBase,
    Ramp,
    Sine,
    Triangle,
)
from wombat.domain.snippets.rhythms import (
    Accelerando,
    ConstantBeat,
    DetectedBeats,
    Euclidean,
    Subdivided,
    Swing,
)

Snippet = Union[BeatSnippet, WaveformSnippet]


@dataclass
class SnippetEntry:
    name: str
    category: str
    snippet: Snippet
    description: str = ""


def _beat(name: str, cat: str, rhythm, pos, desc: str = "") -> SnippetEntry:
    return SnippetEntry(name=name, category=cat,
                        snippet=BeatSnippet(rhythm=rhythm, pos=pos, name=name),
                        description=desc)


def _wave(name: str, cat: str, snippet: WaveformSnippet, desc: str = "") -> SnippetEntry:
    return SnippetEntry(name=name, category=cat, snippet=snippet, description=desc)


PRESETS: list[SnippetEntry] = [
    # ---- Rhythm × Alternate
    _beat("Alternating", "Beat",
          ConstantBeat(bpm=120.0), Alternate(low=0, high=100),
          "Even beats toggling between two positions."),
    _beat("Buzz", "Beat",
          ConstantBeat(bpm=360.0), Alternate(low=20, high=80),
          "High-frequency alternating — vibration feel."),
    _beat("Slow Pulse", "Beat",
          ConstantBeat(bpm=60.0), Alternate(low=10, high=90),
          "Slow deep alternation."),
    _beat("Swing Alternating", "Beat",
          Swing(bpm=120.0, swing_ratio=0.67), Alternate(low=0, high=100),
          "Alternating with swing feel."),
    _beat("Subdivided 16ths", "Beat",
          Subdivided(bpm=120.0, subdivisions=4), Alternate(low=0, high=100),
          "120 BPM in 16th-note subdivisions."),

    # ---- Detected beats (timing from audio analysis of the loaded video)
    _beat("On Beats", "Detected",
          DetectedBeats(), Alternate(low=0, high=100),
          "Alternating positions on each detected beat. Requires beat detection."),
    _beat("On Downbeats", "Detected",
          DetectedBeats(downbeats_only=True), Alternate(low=0, high=100),
          "Alternating positions on each detected downbeat (bar start)."),
    _beat("Throb on Beats", "Detected",
          DetectedBeats(), Sine(amplitude=40.0, frequency=0.5, center=50),
          "Sinusoidal positions sampled at detected beats."),

    # ---- Euclidean patterns
    _beat("Pulse Train 3/8", "Euclidean",
          Euclidean(pulses=3, steps=8, bpm=120.0), Alternate(low=0, high=100),
          "3 pulses in 8 steps — classic Euclidean groove."),
    _beat("Pulse Train 5/8", "Euclidean",
          Euclidean(pulses=5, steps=8, bpm=120.0), Alternate(low=0, high=100),
          "5 pulses in 8 steps."),
    _beat("Pulse Train 7/16", "Euclidean",
          Euclidean(pulses=7, steps=16, bpm=120.0), Alternate(low=0, high=100),
          "7 pulses in 16 steps."),

    # ---- Accelerando
    _beat("Tease", "Tempo",
          Accelerando(bpm_start=60.0, bpm_end=180.0), Alternate(low=20, high=80),
          "Starts slow, speeds up to end."),
    _beat("Slow Down", "Tempo",
          Accelerando(bpm_start=180.0, bpm_end=60.0), Alternate(low=20, high=80),
          "Starts fast, slows to end."),

    # ---- Ramp
    _beat("Rising Ramp", "Ramp",
          ConstantBeat(bpm=120.0), Ramp(start=0, end=100),
          "Beats with linearly rising positions."),
    _beat("Falling Ramp", "Ramp",
          ConstantBeat(bpm=120.0), Ramp(start=100, end=0),
          "Beats with linearly falling positions."),

    # ---- Sine waveform (over beat grid)
    _beat("Throb", "Waveform",
          ConstantBeat(bpm=60.0), Sine(amplitude=40.0, frequency=0.5, center=50),
          "Slow sinusoidal throb."),

    # ---- AlternateOverBase / FollowBase
    _beat("Alternate Over Base", "Layered",
          ConstantBeat(bpm=120.0), AlternateOverBase(low_offset=-30, high_offset=30),
          "Alternating offset added to the underlying signal."),
    _beat("Follow Base", "Layered",
          ConstantBeat(bpm=120.0), FollowBase(scale=1.0, offset=0),
          "Sample and re-emit the underlying signal at beat times."),

    # ---- Dense waveforms (WaveformSnippet)
    _wave("Sine Wave", "Waveform",
          WaveformSnippet(waveform="sine", frequency=1.0, amplitude=45.0, center=50),
          "Continuous sine wave at 1 Hz."),
    _wave("Triangle Wave", "Waveform",
          WaveformSnippet(waveform="triangle", frequency=1.0, amplitude=45.0, center=50),
          "Continuous triangle wave at 1 Hz."),
    _wave("Square Wave", "Waveform",
          WaveformSnippet(waveform="square", frequency=1.0, amplitude=45.0, center=50),
          "Continuous square wave at 1 Hz."),
    _wave("Sawtooth Wave", "Waveform",
          WaveformSnippet(waveform="sawtooth", frequency=1.0, amplitude=45.0, center=50),
          "Continuous sawtooth wave at 1 Hz."),
    _wave("High Frequency Sine", "Waveform",
          WaveformSnippet(waveform="sine", frequency=5.0, amplitude=30.0, center=50),
          "Dense 5 Hz sine — intense vibration."),
]

# Index by name for quick lookup
_REGISTRY: dict[str, SnippetEntry] = {e.name: e for e in PRESETS}


def list_presets() -> list[str]:
    return [e.name for e in PRESETS]


def get_snippet(name: str) -> Snippet | None:
    entry = _REGISTRY.get(name)
    return entry.snippet if entry is not None else None
