"""Tests for Phase 7 — snippet library (domain/snippets/).

Coverage:
- Rhythms: spacing, count, pattern correctness, monotonicity
- Positions: toggle, waveform match, base-dependent, reproducibility, clamp
- BeatSnippet / WaveformSnippet: actions within span, frame-snap, density
- Library: every preset builds a valid snippet with default params
- ParamSpec: defaults produce well-formed controls
- Editor: insert_snippet_as_layer adds one layer + one undo step; base sampler works
- Domain isolation: no Qt import in domain/snippets/
"""
from __future__ import annotations

import math
import sys

import numpy as np
import pytest

from wombat.domain.action import Action, ActionList
from wombat.domain.snippets.base import BeatSnippet, WaveformSnippet
from wombat.domain.snippets.library import PRESETS, get_snippet, list_presets
from wombat.domain.snippets.positions import (
    Alternate,
    AlternateOverBase,
    Constant,
    FollowBase,
    Ramp,
    Random,
    Sawtooth,
    Sine,
    Square,
    Triangle,
)
from wombat.domain.snippets.rhythms import (
    Accelerando,
    ConstantBeat,
    Euclidean,
    Subdivided,
    Swing,
    _euclidean_pattern,
)


# ================================================================ helpers

def _al(*pairs) -> ActionList:
    return ActionList(Action(t, p) for t, p in pairs)


SPAN = (0.0, 4.0)


# ================================================================ ConstantBeat

def test_constant_beat_spacing():
    r = ConstantBeat(bpm=60.0)
    times = r.beats(SPAN, None)
    # 60 BPM = 1 beat/s → 5 beats in [0,4]
    assert len(times) == 5
    diffs = np.diff(times)
    assert np.allclose(diffs, 1.0, atol=1e-9)


def test_constant_beat_bpm_scales():
    r = ConstantBeat(bpm=120.0)
    times = r.beats(SPAN, None)
    # 120 BPM = 2 beats/s → 9 beats in [0,4]
    assert len(times) == 9
    diffs = np.diff(times)
    assert np.allclose(diffs, 0.5, atol=1e-9)


def test_constant_beat_offset():
    r = ConstantBeat(bpm=60.0, offset=0.5)
    times = r.beats(SPAN, None)
    assert times[0] == pytest.approx(0.5)


def test_constant_beat_all_in_span():
    r = ConstantBeat(bpm=60.0)
    times = r.beats(SPAN, None)
    assert all(SPAN[0] <= t <= SPAN[1] + 1e-9 for t in times)


# ================================================================ Subdivided

def test_subdivided_count():
    r = Subdivided(bpm=60.0, subdivisions=4)
    times = r.beats(SPAN, None)
    # 60 BPM with 4 subdivisions = 4 hits/s → 17 in [0,4]
    assert len(times) == 17


def test_subdivided_spacing():
    r = Subdivided(bpm=120.0, subdivisions=2)
    times = r.beats(SPAN, None)
    diffs = np.diff(times)
    expected = 60.0 / (120.0 * 2)
    assert np.allclose(diffs, expected, atol=1e-9)


# ================================================================ Swing

def test_swing_alternates_long_short():
    r = Swing(bpm=120.0, swing_ratio=0.67)
    times = r.beats(SPAN, None)
    diffs = np.diff(times)
    # Should alternate long/short
    longs = diffs[0::2]
    shorts = diffs[1::2]
    assert np.all(longs > shorts)


def test_swing_straight_is_even():
    r = Swing(bpm=120.0, swing_ratio=0.5)
    times = r.beats(SPAN, None)
    diffs = np.diff(times)
    assert np.allclose(diffs, diffs[0], atol=1e-6)


def test_swing_all_in_span():
    r = Swing(bpm=120.0, swing_ratio=0.67)
    times = r.beats(SPAN, None)
    assert all(SPAN[0] <= t <= SPAN[1] + 1e-9 for t in times)


# ================================================================ Euclidean

def test_euclidean_pattern_3_8():
    p = _euclidean_pattern(3, 8)
    assert len(p) == 8
    assert sum(p) == 3


def test_euclidean_pattern_all_pulses():
    p = _euclidean_pattern(8, 8)
    assert all(p)


def test_euclidean_pattern_no_pulses():
    p = _euclidean_pattern(0, 8)
    assert not any(p)


def test_euclidean_pattern_5_8():
    p = _euclidean_pattern(5, 8)
    assert sum(p) == 5
    assert len(p) == 8


def test_euclidean_beats_repeats_pattern():
    r = Euclidean(pulses=3, steps=8, bpm=60.0)
    times = r.beats((0.0, 16.0), None)
    # Should have hits, all within span
    assert len(times) > 0
    assert all(0.0 <= t <= 16.0 + 1e-9 for t in times)


# ================================================================ Accelerando

def test_accelerando_monotonic():
    r = Accelerando(bpm_start=60.0, bpm_end=180.0)
    times = r.beats(SPAN, None)
    assert len(times) >= 2
    diffs = np.diff(times)
    assert np.all(diffs > 0), "Times must be monotonically increasing"


def test_accelerando_spacing_decreases():
    """Tempo speeds up → inter-beat intervals shrink."""
    r = Accelerando(bpm_start=60.0, bpm_end=180.0)
    times = r.beats(SPAN, None)
    diffs = np.diff(times)
    if len(diffs) >= 2:
        assert diffs[-1] < diffs[0], "Intervals should shrink as tempo increases"


def test_accelerando_all_in_span():
    r = Accelerando(bpm_start=60.0, bpm_end=180.0)
    times = r.beats(SPAN, None)
    assert all(SPAN[0] <= t <= SPAN[1] + 1e-9 for t in times)


# ================================================================ Alternate position

def test_alternate_toggles():
    pos = Alternate(low=10, high=90)
    times = np.array([0.0, 1.0, 2.0, 3.0])
    result = pos.positions(times, None)
    assert result[0] == pytest.approx(90.0)
    assert result[1] == pytest.approx(10.0)
    assert result[2] == pytest.approx(90.0)
    assert result[3] == pytest.approx(10.0)


def test_alternate_empty():
    pos = Alternate()
    result = pos.positions(np.array([]), None)
    assert len(result) == 0


# ================================================================ Constant

def test_constant_all_same():
    pos = Constant(value=42)
    times = np.linspace(0, 1, 10)
    result = pos.positions(times, None)
    assert np.all(result == pytest.approx(42.0))


# ================================================================ Ramp

def test_ramp_endpoints():
    pos = Ramp(start=0, end=100)
    times = np.array([0.0, 0.5, 1.0])
    result = pos.positions(times, None)
    assert result[0] == pytest.approx(0.0)
    assert result[-1] == pytest.approx(100.0)


def test_ramp_single_point():
    pos = Ramp(start=30, end=70)
    result = pos.positions(np.array([0.5]), None)
    assert result[0] == pytest.approx(30.0)


# ================================================================ Random

def test_random_reproducible():
    pos = Random(low=0, high=100, seed=99)
    times = np.linspace(0, 1, 20)
    r1 = pos.positions(times, None)
    r2 = pos.positions(times, None)
    assert np.allclose(r1, r2)


def test_random_different_seeds():
    times = np.linspace(0, 1, 20)
    r1 = Random(seed=1).positions(times, None)
    r2 = Random(seed=2).positions(times, None)
    assert not np.allclose(r1, r2)


def test_random_within_range():
    pos = Random(low=20, high=80, seed=7)
    times = np.linspace(0, 1, 100)
    result = pos.positions(times, None)
    assert np.all(result >= 20.0)
    assert np.all(result <= 80.0)


# ================================================================ Waveform positions

def test_sine_at_zero_phase():
    """Sine at t=0 with phase=0 → center (sin(0)=0)."""
    pos = Sine(amplitude=50.0, frequency=1.0, center=50, phase=0.0)
    times = np.array([0.0])
    result = pos.positions(times, None)
    assert result[0] == pytest.approx(50.0, abs=1e-6)


def test_sine_quarter_cycle():
    """Sine at t=quarter period → center + amplitude."""
    freq = 1.0
    pos = Sine(amplitude=50.0, frequency=freq, center=50, phase=0.0)
    t_quarter = 1.0 / (4 * freq)
    times = np.array([0.0, t_quarter])
    result = pos.positions(times, None)
    assert result[1] == pytest.approx(100.0, abs=1e-4)


def test_triangle_bounded():
    pos = Triangle(amplitude=50.0, frequency=1.0, center=50)
    times = np.linspace(0, 2, 200)
    result = pos.positions(times, None)
    assert np.all(result >= 0.0 - 1e-6)
    assert np.all(result <= 100.0 + 1e-6)


def test_square_only_two_values():
    pos = Square(amplitude=50.0, frequency=1.0, center=50, phase=0.0)
    times = np.linspace(0.01, 1.99, 100)  # avoid zero-crossing ambiguity
    result = pos.positions(times, None)
    unique = set(np.round(result, 6))
    assert len(unique) <= 2


def test_sawtooth_range():
    pos = Sawtooth(amplitude=50.0, frequency=1.0, center=50)
    times = np.linspace(0, 2, 200)
    result = pos.positions(times, None)
    assert np.all(result >= 0.0 - 1e-6)
    assert np.all(result <= 100.0 + 1e-6)


# ================================================================ AlternateOverBase

def test_alternate_over_base_adds_offset():
    base_al = _al((0.0, 60), (4.0, 60))  # flat at 60
    sampler = lambda ts: np.full(len(ts), 60.0)  # noqa: E731
    pos = AlternateOverBase(low_offset=-10, high_offset=20)
    times = np.array([0.0, 1.0, 2.0, 3.0])
    result = pos.positions(times, sampler)
    assert result[0] == pytest.approx(80.0)   # 60 + 20
    assert result[1] == pytest.approx(50.0)   # 60 - 10


def test_alternate_over_base_no_sampler_uses_50():
    pos = AlternateOverBase(low_offset=-10, high_offset=10)
    times = np.array([0.0, 1.0])
    result = pos.positions(times, None)
    assert result[0] == pytest.approx(60.0)   # 50 + 10
    assert result[1] == pytest.approx(40.0)   # 50 - 10


# ================================================================ FollowBase

def test_follow_base_scale_one():
    sampler = lambda ts: np.full(len(ts), 70.0)  # noqa: E731
    pos = FollowBase(scale=1.0, offset=0)
    times = np.linspace(0, 1, 5)
    result = pos.positions(times, sampler)
    assert np.allclose(result, 70.0)


def test_follow_base_with_offset():
    sampler = lambda ts: np.full(len(ts), 50.0)  # noqa: E731
    pos = FollowBase(scale=1.0, offset=10)
    times = np.array([0.5])
    result = pos.positions(times, sampler)
    assert result[0] == pytest.approx(60.0)


def test_follow_base_no_sampler():
    pos = FollowBase(scale=2.0, offset=0)
    times = np.array([0.0])
    result = pos.positions(times, None)
    assert result[0] == pytest.approx(100.0)  # 50 * 2


# ================================================================ BeatSnippet

def test_beat_snippet_actions_within_span():
    snippet = BeatSnippet(ConstantBeat(bpm=60.0), Alternate())
    al = snippet.generate(SPAN)
    assert len(al) > 0
    for a in al:
        assert SPAN[0] <= a.at <= SPAN[1] + 1e-9


def test_beat_snippet_positions_clamped():
    snippet = BeatSnippet(ConstantBeat(bpm=60.0), Alternate(low=0, high=100))
    al = snippet.generate(SPAN)
    for a in al:
        assert 0 <= a.pos <= 100


def test_beat_snippet_frame_snap():
    fps = 30.0
    snippet = BeatSnippet(ConstantBeat(bpm=60.0), Alternate())
    al = snippet.generate(SPAN, fps=fps, snap_to_frame=True)
    frame_time = 1.0 / fps
    for a in al:
        # Should be a multiple of frame_time (within float rounding)
        n = round(a.at / frame_time)
        assert abs(a.at - n * frame_time) < 1e-6, f"t={a.at} not frame-aligned"


def test_beat_snippet_base_sampler():
    """A base-dependent pos reads from the ActionList passed as base."""
    base_al = _al((0.0, 70), (4.0, 70))  # flat at 70
    snippet = BeatSnippet(ConstantBeat(bpm=60.0), AlternateOverBase(low_offset=0, high_offset=0))
    al = snippet.generate(SPAN, base=base_al)
    # high_offset=0, low_offset=0 → all positions should be 70
    for a in al:
        assert a.pos == 70


def test_beat_snippet_degenerate_span():
    """Degenerate span produces at most 1 action (the boundary point)."""
    snippet = BeatSnippet(ConstantBeat(bpm=60.0), Alternate())
    al = snippet.generate((2.0, 2.0))
    assert len(al) <= 1


# ================================================================ WaveformSnippet

def test_waveform_snippet_density():
    snippet = WaveformSnippet(waveform="sine", resolution_hz=60.0)
    span = (0.0, 2.0)
    al = snippet.generate(span)
    expected_min = int(2.0 * 60.0 * 0.8)  # 80% of expected
    assert len(al) >= expected_min, f"Too few points: {len(al)}"


def test_waveform_snippet_actions_in_span():
    snippet = WaveformSnippet(waveform="triangle", frequency=2.0, amplitude=40.0)
    span = (1.0, 3.0)
    al = snippet.generate(span)
    for a in al:
        assert 1.0 <= a.at <= 3.0 + 1e-9


def test_waveform_snippet_clamped():
    snippet = WaveformSnippet(waveform="sine", amplitude=100.0, center=50)
    al = snippet.generate(SPAN)
    for a in al:
        assert 0 <= a.pos <= 100


def test_waveform_snippet_all_waveforms():
    for wf in ["sine", "triangle", "square", "sawtooth"]:
        snippet = WaveformSnippet(waveform=wf, frequency=1.0, amplitude=40.0)
        al = snippet.generate(SPAN)
        assert len(al) > 0, f"Waveform {wf!r} produced no actions"


def test_waveform_snippet_frame_snap():
    fps = 24.0
    snippet = WaveformSnippet(waveform="sine", resolution_hz=60.0)
    al = snippet.generate(SPAN, fps=fps, snap_to_frame=True)
    frame_time = 1.0 / fps
    for a in al:
        n = round(a.at / frame_time)
        assert abs(a.at - n * frame_time) < 1e-4, f"t={a.at} not frame-aligned"


# ================================================================ Library

def test_library_list_presets_non_empty():
    names = list_presets()
    assert len(names) > 0


def test_library_get_snippet_known():
    for name in list_presets():
        s = get_snippet(name)
        assert s is not None, f"get_snippet({name!r}) returned None"


def test_library_get_snippet_unknown():
    assert get_snippet("no such snippet") is None


def test_library_all_presets_generate():
    """Every preset in the registry can generate actions over a simple span."""
    span = (0.0, 2.0)
    for entry in PRESETS:
        try:
            al = entry.snippet.generate(span)
        except Exception as exc:
            pytest.fail(f"Preset {entry.name!r} raised: {exc}")
        assert isinstance(al, ActionList), f"Preset {entry.name!r} returned non-ActionList"


def test_library_all_param_specs_valid():
    """Every generator's param_specs() produce well-formed ParamSpec objects.

    We check attributes rather than isinstance() to be robust against the
    module-reload that test_channel::test_domain_does_not_import_pyside6
    performs on all wombat.domain.* modules.
    """
    for entry in PRESETS:
        snippet = entry.snippet
        if isinstance(snippet, WaveformSnippet):
            specs = WaveformSnippet.param_specs()
        elif isinstance(snippet, BeatSnippet):
            specs = type(snippet.rhythm).param_specs() + type(snippet.pos).param_specs()
        else:
            specs = []
        for spec in specs:
            # duck-type check: must have ParamSpec fields
            assert hasattr(spec, "key") and hasattr(spec, "label") and hasattr(spec, "kind"), (
                f"Not a ParamSpec-like object in {entry.name!r}: {spec!r}"
            )
            assert spec.key and spec.label, f"Empty key/label in {entry.name!r}"
            assert spec.kind in ("int", "float", "bool", "choice"), (
                f"Invalid kind {spec.kind!r} in {entry.name!r}.{spec.key}"
            )
            if spec.min is not None and spec.max is not None:
                assert spec.min <= spec.max, f"min > max in {entry.name!r}.{spec.key}"


# ================================================================ domain isolation

def test_snippets_no_qt_import():
    """domain/snippets source files must not import PySide6 (static AST check)."""
    import ast
    import pathlib
    import importlib

    pkg = importlib.import_module("wombat.domain.snippets")
    pkg_dir = pathlib.Path(pkg.__file__).parent

    for py_file in pkg_dir.glob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("PySide6"), (
                        f"{py_file.name} imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not mod.startswith("PySide6"), (
                    f"{py_file.name} imports from {mod}"
                )


# ================================================================ editor integration

def test_editor_insert_snippet_as_layer():
    """insert_snippet_as_layer adds exactly one new layer and one undo step."""
    import sys
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)

    from wombat.app.editor import EditorController
    from wombat.app.project import Project
    from wombat.app.undo import UndoStack
    from wombat.domain.channel import Channel, Layer

    ch = Channel(name="c", layers=[Layer(actions=_al((0.0, 0), (4.0, 100)))])
    project = Project.new()
    project.channels.append(ch)
    player = MagicMock()
    player.frame_time = 1.0 / 30.0
    undo = UndoStack()
    ed = EditorController(project, player, undo)

    snippet = BeatSnippet(ConstantBeat(bpm=60.0), Alternate())
    initial_layers = len(ch.layers)
    ed.insert_snippet_as_layer(snippet, (0.0, 4.0), name="test")

    assert len(ch.layers) == initial_layers + 1
    assert ed.can_undo


def test_editor_insert_snippet_layer_content():
    """The inserted layer contains actions generated by the snippet."""
    import sys
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)

    from wombat.app.editor import EditorController
    from wombat.app.project import Project
    from wombat.app.undo import UndoStack
    from wombat.domain.channel import Channel, Layer

    ch = Channel(name="c", layers=[Layer(actions=_al((0.0, 0), (4.0, 100)))])
    project = Project.new()
    project.channels.append(ch)
    player = MagicMock()
    player.frame_time = 1.0 / 30.0
    undo = UndoStack()
    ed = EditorController(project, player, undo)

    snippet = BeatSnippet(ConstantBeat(bpm=60.0), Alternate())
    ed.insert_snippet_as_layer(snippet, (0.0, 4.0), name="test")

    new_layer = ch.layers[ed.active_layer_index]
    assert len(new_layer.actions) > 0
    assert new_layer.name == "test"


def test_editor_insert_undo():
    """Undoing an insert_snippet_as_layer removes the layer."""
    import sys
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)

    from wombat.app.editor import EditorController
    from wombat.app.project import Project
    from wombat.app.undo import UndoStack
    from wombat.domain.channel import Channel, Layer

    ch = Channel(name="c", layers=[Layer(actions=_al((0.0, 0), (4.0, 100)))])
    project = Project.new()
    project.channels.append(ch)
    player = MagicMock()
    player.frame_time = 1.0 / 30.0
    undo = UndoStack()
    ed = EditorController(project, player, undo)

    snippet = BeatSnippet(ConstantBeat(bpm=60.0), Alternate())
    initial_count = len(ch.layers)
    ed.insert_snippet_as_layer(snippet, (0.0, 4.0))
    assert len(ch.layers) == initial_count + 1

    ed.undo()
    assert len(ch.layers) == initial_count
