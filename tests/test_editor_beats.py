"""Tests for snap-to-beats in EditorController."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.app.editor import EditorController  # noqa: E402
from wombat.app.project import Project  # noqa: E402
from wombat.app.undo import UndoStack  # noqa: E402
from wombat.audio.beats import BeatGrid  # noqa: E402
from wombat.domain.action import Action, ActionList  # noqa: E402
from wombat.domain.channel import Channel, Layer  # noqa: E402


def _player_stub(fps: float = 30.0) -> MagicMock:
    p = MagicMock()
    p.frame_time = 1.0 / fps if fps > 0 else 0.0
    return p


def _editor(*pairs, fps: float = 30.0):
    al = ActionList(Action(t, p) for t, p in pairs)
    ch = Channel(name="c", layers=[Layer(actions=al)])
    project = Project.new()
    project.channels.append(ch)
    ed = EditorController(project, _player_stub(fps), UndoStack())
    return ed, ch


def _grid() -> BeatGrid:
    return BeatGrid(
        np.array([0.5, 1.03, 1.5, 2.0], dtype=np.float64),
        np.array([1, 2, 3, 1], dtype=np.int32),
    )


def test_add_action_snaps_to_nearest_beat():
    ed, ch = _editor()
    ed.set_beats(_grid())
    ed.snap_to_beats = True
    ed.add_action(1.2, 50)   # nearest beat is 1.03
    assert ch.layers[0].actions[0].at == pytest.approx(1.03)


def test_add_action_no_beat_snap_when_disabled():
    ed, ch = _editor()
    ed.set_beats(_grid())
    ed.add_action(1.2, 50)
    assert ch.layers[0].actions[0].at == pytest.approx(1.2)


def test_beat_snap_noop_without_grid():
    ed, ch = _editor()
    ed.snap_to_beats = True   # enabled but no grid set
    ed.add_action(1.2, 50)
    assert ch.layers[0].actions[0].at == pytest.approx(1.2)


def test_beat_snap_noop_with_empty_grid():
    ed, ch = _editor()
    ed.set_beats(BeatGrid.empty())
    ed.snap_to_beats = True
    ed.add_action(1.2, 50)
    assert ch.layers[0].actions[0].at == pytest.approx(1.2)


def test_beats_then_frame_quantize():
    # beat snap to 1.03, then frame-quantize (0.1s) → 1.0
    ed, ch = _editor(fps=10.0)
    ed.set_beats(_grid())
    ed.snap_to_beats = True
    ed.snap_to_frame = True
    ed.add_action(1.2, 50)
    assert ch.layers[0].actions[0].at == pytest.approx(1.0)


def test_edit_action_snaps_to_beat():
    ed, ch = _editor((0.5, 10))
    ed.set_beats(_grid())
    ed.snap_to_beats = True
    ed.edit_action(0.5, 1.4, 80)   # nearest beat to 1.4 is 1.5
    ats = [a.at for a in ch.layers[0].actions]
    assert ats == pytest.approx([1.5])


def test_move_selection_snaps_to_beat():
    ed, ch = _editor((0.5, 10))
    ed.set_beats(_grid())
    ed.snap_to_beats = True
    ed.select(0.5)
    ed.begin_move()
    ed.move_selection(1.6, 0)   # 0.5 + 1.6 = 2.1 → nearest beat 2.0
    ed.end_move()
    ats = [a.at for a in ch.layers[0].actions]
    assert ats == pytest.approx([2.0])
