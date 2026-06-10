"""Tests for EditorController — edits, gestures, selection, transforms, clipboard."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# QApplication is required for QObject/Signal — create once before Qt imports.
# conftest.py already called ensure_libmpv, so mpv import is safe.
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.app.editor import EditorController  # noqa: E402
from wombat.app.session import Session  # noqa: E402
from wombat.app.undo import UndoStack  # noqa: E402
from wombat.domain.action import Action, ActionList  # noqa: E402
from wombat.domain.channel import Channel, Layer  # noqa: E402, I001

# ------------------------------------------------------------------ fixtures

def _player_stub(fps: float = 30.0) -> MagicMock:
    p = MagicMock()
    p.frame_time = 1.0 / fps if fps > 0 else 0.0
    return p


def _channel(*pairs) -> Channel:
    al = ActionList(Action(t, p) for t, p in pairs)
    return Channel(name="c", layers=[Layer(actions=al)])


def _editor(*pairs, fps: float = 30.0) -> tuple[EditorController, Channel]:
    ch = _channel(*pairs)
    session = Session(player=_player_stub(fps), channels=[ch])
    undo = UndoStack()
    ed = EditorController(session, undo)
    return ed, ch


# ------------------------------------------------------------------ add_action

def test_add_action_inserts():
    ed, ch = _editor()
    ed.add_action(1.0, 50)
    assert len(ch.layers[0].actions) == 1
    assert ch.layers[0].actions[0] == Action(1.0, 50)


def test_add_action_creates_undo_step():
    ed, ch = _editor()
    ed.add_action(1.0, 50)
    assert ed.can_undo


def test_add_action_snaps_to_frame():
    ed, ch = _editor(fps=10.0)  # frame_time = 0.1s
    ed.snap_to_frame = True
    ed.add_action(0.123, 50)  # nearest frame = 0.1
    assert ch.layers[0].actions[0].at == pytest.approx(0.1)


def test_add_action_no_snap_by_default():
    ed, ch = _editor(fps=10.0)
    ed.add_action(0.123, 50)
    assert ch.layers[0].actions[0].at == pytest.approx(0.123)


# ------------------------------------------------------------------ remove_action

def test_remove_action_deletes():
    ed, ch = _editor((1.0, 50), (2.0, 100))
    ed.remove_action(1.0)
    assert len(ch.layers[0].actions) == 1
    assert ch.layers[0].actions[0].at == pytest.approx(2.0)


def test_remove_action_missing_is_noop():
    ed, ch = _editor((1.0, 50))
    ed.remove_action(99.0)  # should not raise
    assert len(ch.layers[0].actions) == 1


def test_remove_action_updates_selection():
    ed, ch = _editor((1.0, 50), (2.0, 100))
    ed.select(1.0)
    ed.remove_action(1.0)
    assert 1.0 not in ed.selection


# ------------------------------------------------------------------ remove_selection

def test_remove_selection_deletes_all_selected():
    ed, ch = _editor((1.0, 0), (2.0, 50), (3.0, 100))
    ed.select_all()
    ed.remove_selection()
    assert len(ch.layers[0].actions) == 0


def test_remove_selection_is_one_undo_step():
    ed, ch = _editor((1.0, 0), (2.0, 50), (3.0, 100))
    ed.select_all()
    ed.remove_selection()
    assert ed.can_undo
    ed.undo()
    assert len(ch.layers[0].actions) == 3


# ------------------------------------------------------------------ edit_action

def test_edit_action_updates_at_and_pos():
    ed, ch = _editor((1.0, 50))
    ed.edit_action(1.0, 1.5, 75)
    assert len(ch.layers[0].actions) == 1
    assert ch.layers[0].actions[0] == Action(1.5, 75)


def test_edit_action_updates_selection_key():
    ed, ch = _editor((1.0, 50))
    ed.select(1.0)
    ed.edit_action(1.0, 1.5, 75)
    assert 1.5 in ed.selection
    assert 1.0 not in ed.selection


# ------------------------------------------------------------------ move gesture

def test_move_selection_shifts_at():
    ed, ch = _editor((1.0, 50), (2.0, 75))
    ed.select(1.0)
    ed.begin_move()
    ed.move_selection(0.5, 0)
    ed.end_move()
    ats = [a.at for a in ch.layers[0].actions]
    assert any(abs(a - 1.5) < 1e-9 for a in ats)


def test_move_gesture_is_one_undo_step():
    ed, ch = _editor((1.0, 50), (2.0, 75))
    ed.select_all()
    ed.begin_move()
    ed.move_selection(1.0, 0)
    ed.move_selection(2.0, 0)  # several intermediate moves
    ed.end_move()
    assert ed.can_undo
    ed.undo()
    # restored to original
    ats = [a.at for a in ch.layers[0].actions]
    assert any(abs(t - 1.0) < 1e-9 for t in ats)
    assert any(abs(t - 2.0) < 1e-9 for t in ats)


def test_move_updates_selection_keys():
    ed, ch = _editor((1.0, 50))
    ed.select(1.0)
    ed.begin_move()
    ed.move_selection(0.5, 0)
    ed.end_move()
    assert 1.5 in ed.selection
    assert 1.0 not in ed.selection


def test_cancel_move_restores():
    ed, ch = _editor((1.0, 50))
    ed.select(1.0)
    ed.begin_move()
    ed.move_selection(5.0, 0)
    ed.cancel_move()
    assert ch.layers[0].actions[0].at == pytest.approx(1.0)
    assert not ed.can_undo


# ------------------------------------------------------------------ selection

def test_select_single():
    ed, ch = _editor((1.0, 0), (2.0, 50))
    ed.select(1.0)
    assert ed.selection == frozenset({1.0})


def test_select_additive():
    ed, ch = _editor((1.0, 0), (2.0, 50))
    ed.select(1.0)
    ed.select(2.0, additive=True)
    assert ed.selection == frozenset({1.0, 2.0})


def test_select_non_additive_replaces():
    ed, ch = _editor((1.0, 0), (2.0, 50))
    ed.select(1.0)
    ed.select(2.0, additive=False)
    assert ed.selection == frozenset({2.0})


def test_select_all():
    ed, ch = _editor((1.0, 0), (2.0, 50), (3.0, 100))
    ed.select_all()
    assert ed.selection == frozenset({1.0, 2.0, 3.0})


def test_clear_selection():
    ed, ch = _editor((1.0, 0), (2.0, 50))
    ed.select_all()
    ed.clear_selection()
    assert ed.selection == frozenset()


def test_invert_selection():
    ed, ch = _editor((1.0, 0), (2.0, 50), (3.0, 100))
    ed.select(1.0)
    ed.invert_selection()
    assert ed.selection == frozenset({2.0, 3.0})


def test_select_time_range():
    ed, ch = _editor((1.0, 0), (2.0, 50), (3.0, 100), (4.0, 75))
    ed.select_time_range(1.5, 3.5)
    assert ed.selection == frozenset({2.0, 3.0})


def test_select_time_range_additive():
    ed, ch = _editor((1.0, 0), (2.0, 50), (3.0, 100))
    ed.select(1.0)
    ed.select_time_range(2.0, 3.0, additive=True)
    assert ed.selection == frozenset({1.0, 2.0, 3.0})


def test_select_top():
    ed, ch = _editor((0.0, 0), (1.0, 100), (2.0, 0))
    ed.select_top()
    assert 1.0 in ed.selection


def test_select_bottom():
    ed, ch = _editor((0.0, 100), (1.0, 0), (2.0, 100))
    ed.select_bottom()
    assert 1.0 in ed.selection


# ------------------------------------------------------------------ transforms

def test_equalize_selection():
    ed, ch = _editor((0.0, 0), (1.0, 50), (4.0, 100))
    ed.select_all()
    ed.equalize_selection()
    ats = sorted(a.at for a in ch.layers[0].actions)
    # equalized: 0, 2, 4
    assert ats[1] == pytest.approx(2.0)


def test_equalize_is_undoable():
    ed, ch = _editor((0.0, 0), (2.0, 50), (4.0, 100))
    ed.select_all()
    ed.equalize_selection()
    assert ed.can_undo
    ed.undo()
    # timestamps restored
    ats = sorted(a.at for a in ch.layers[0].actions)
    assert ats == pytest.approx([0.0, 2.0, 4.0])


def test_invert_positions():
    ed, ch = _editor((0.0, 0), (1.0, 100))
    ed.select_all()
    ed.invert_positions()
    positions = [a.pos for a in ch.layers[0].actions]
    assert positions == [100, 0]


def test_simplify_removes_midpoints():
    # Three collinear points: middle should be removed
    ed, ch = _editor((0.0, 0), (1.0, 50), (2.0, 100))
    ed.select_all()
    ed.simplify_selection(epsilon=1.0)
    assert len(ch.layers[0].actions) == 2


# ------------------------------------------------------------------ clipboard

def test_copy_paste_at_playhead():
    ed, ch = _editor((1.0, 50), (2.0, 75))
    ed.select_all()
    ed.copy()
    # paste at t=5 → offsets should be 0 and 1
    ed.paste(5.0)
    ats = sorted(a.at for a in ch.layers[0].actions)
    assert any(abs(t - 5.0) < 1e-9 for t in ats)
    assert any(abs(t - 6.0) < 1e-9 for t in ats)


def test_paste_selects_new_actions():
    ed, ch = _editor((1.0, 50))
    ed.select_all()
    ed.copy()
    ed.clear_selection()
    ed.paste(3.0)
    assert 3.0 in ed.selection


def test_paste_exact_restores_absolute_times():
    ed, ch = _editor((1.0, 50), (2.0, 75))
    ed.select_all()
    ed.copy()
    ed.paste_exact()
    # re-inserts at same times (replaces existing)
    ats = sorted(a.at for a in ch.layers[0].actions)
    assert ats == pytest.approx([1.0, 2.0])


def test_cut_removes_and_clipboard():
    ed, ch = _editor((1.0, 50), (2.0, 75), (3.0, 100))
    ed.select(2.0)
    ed.cut()
    assert 2.0 not in [a.at for a in ch.layers[0].actions]
    # paste should bring it back at playhead
    ed.paste(5.0)
    assert any(abs(a.at - 5.0) < 1e-6 for a in ch.layers[0].actions)


# ------------------------------------------------------------------ undo/redo

def test_undo_redo_roundtrip():
    ed, ch = _editor()
    ed.add_action(1.0, 50)
    ed.add_action(2.0, 75)
    ed.undo()
    assert len(ch.layers[0].actions) == 1
    ed.redo()
    assert len(ch.layers[0].actions) == 2


def test_can_undo_redo_properties():
    ed, ch = _editor()
    assert not ed.can_undo
    assert not ed.can_redo
    ed.add_action(1.0, 50)
    assert ed.can_undo
    ed.undo()
    assert ed.can_redo


# ------------------------------------------------------------------ synthesis cache

def test_synthesize_cache_hit():
    ch = _channel((0.0, 0), (1.0, 100))
    r1 = ch.synthesize()
    r2 = ch.synthesize()
    assert r1 is r2  # same cached object


def test_synthesize_cache_invalidated_by_editor():
    ed, ch = _editor((0.0, 0))
    _ = ch.synthesize()
    assert ch._synthesis_cache is not None
    ed.add_action(1.0, 50)
    assert ch._synthesis_cache is None


def test_synthesize_after_edit_reflects_new_state():
    ed, ch = _editor((0.0, 0))
    ed.add_action(1.0, 100)
    result = ch.synthesize()
    assert len(result) == 2


# ------------------------------------------------------------------ no active channel guard

def test_no_active_channel_is_noop():
    session = Session(player=_player_stub(), channels=[])
    undo = UndoStack()
    ed = EditorController(session, undo)
    # These should not raise
    ed.add_action(1.0, 50)
    ed.remove_selection()
    assert not ed.can_undo
