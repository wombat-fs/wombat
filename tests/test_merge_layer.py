"""Tests for EditorController.merge_layer_down (merge a layer into the one below)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.app.editor import EditorController  # noqa: E402
from wombat.app.project import Project  # noqa: E402
from wombat.app.undo import UndoStack  # noqa: E402
from wombat.domain.action import Action, ActionList  # noqa: E402
from wombat.domain.channel import BlendMode, Channel, Layer  # noqa: E402


def _editor(*layers: Layer) -> tuple[EditorController, Channel]:
    ch = Channel(name="c", layers=list(layers))
    project = Project.new()
    project.channels.append(ch)
    player = MagicMock()
    player.frame_time = 1.0 / 30.0
    ed = EditorController(project, player, UndoStack())
    return ed, ch


def _layer(pairs, **kw) -> Layer:
    return Layer(actions=ActionList(Action(t, p) for t, p in pairs), **kw)


def test_merge_override_into_base():
    base = _layer([(0.0, 0), (10.0, 0)], name="base")
    top = _layer([(0.0, 80), (10.0, 80)], name="edit", blend=BlendMode.OVERRIDE)
    ed, ch = _editor(base, top)
    ed.merge_layer_down(1)
    assert len(ch.layers) == 1
    assert all(a.pos == 80 for a in ch.layers[0].actions)
    assert ch.layers[0].name == "base"   # lower layer's identity preserved


def test_merge_additive_into_base():
    base = _layer([(0.0, 50), (10.0, 50)], name="base")
    top = _layer([(0.0, 70), (10.0, 70)], name="add", blend=BlendMode.ADDITIVE, center=50)
    ed, ch = _editor(base, top)
    ed.merge_layer_down(1)
    assert len(ch.layers) == 1
    # additive: base 50 + (70 - center 50) = 70
    assert all(a.pos == 70 for a in ch.layers[0].actions)


def test_merge_preserves_lower_blend_and_span():
    base = _layer([(0.0, 0), (10.0, 0)], name="base")
    mid = _layer([(0.0, 60)], name="mid", blend=BlendMode.ADDITIVE, span=(2.0, 8.0))
    top = _layer([(0.0, 90), (10.0, 90)], name="top", blend=BlendMode.OVERRIDE)
    ed, ch = _editor(base, mid, top)
    ed.merge_layer_down(2)   # merge top into mid
    assert len(ch.layers) == 2
    merged = ch.layers[1]
    assert merged.name == "mid"
    assert merged.blend == BlendMode.ADDITIVE
    assert merged.span == (2.0, 8.0)


def test_merge_base_is_noop():
    base = _layer([(0.0, 0)], name="base")
    top = _layer([(0.0, 80)], name="top")
    ed, ch = _editor(base, top)
    ed.merge_layer_down(0)   # nothing below the base
    assert len(ch.layers) == 2
    assert not ed.can_undo


def test_merge_is_one_undo_step():
    base = _layer([(0.0, 0), (10.0, 0)], name="base")
    top = _layer([(0.0, 80), (10.0, 80)], name="top")
    ed, ch = _editor(base, top)
    ed.merge_layer_down(1)
    assert len(ch.layers) == 1
    assert ed.can_undo
    ed.undo()
    assert len(ch.layers) == 2
    assert ch.layers[1].name == "top"


def test_merge_clamps_active_layer_index():
    base = _layer([(0.0, 0)], name="base")
    top = _layer([(0.0, 80)], name="top")
    ed, ch = _editor(base, top)
    ed.set_active_layer_index(1)   # active = the upper layer being merged away
    ed.merge_layer_down(1)
    assert ed.active_layer_index == 0   # falls onto the merged result
