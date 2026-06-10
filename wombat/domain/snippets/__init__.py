"""Snippet library — parameterized pattern generators for layer content.

The design separates two orthogonal concerns:
  Rhythm      → when beats happen (the `at` timestamps)
  PosAlgorithm → what position at each beat (the `pos` values)

A BeatSnippet = Rhythm × PosAlgorithm.
A WaveformSnippet emits a dense waveform independently of a beat grid.

Both implement Snippet.generate(span, *, base, fps, snap_to_frame) -> ActionList
so the UI and editor treat them uniformly.
"""
from wombat.domain.snippets.base import BeatSnippet, ParamSpec, WaveformSnippet
from wombat.domain.snippets.library import PRESETS, SnippetEntry, get_snippet, list_presets

__all__ = [
    "BeatSnippet",
    "ParamSpec",
    "WaveformSnippet",
    "PRESETS",
    "SnippetEntry",
    "get_snippet",
    "list_presets",
]
