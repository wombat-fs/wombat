"""Tests for ChannelsPanel layer ordering (top-of-stack shown first)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.app.editor import EditorController  # noqa: E402
from wombat.app.project import Project  # noqa: E402
from wombat.app.undo import UndoStack  # noqa: E402
from wombat.domain.action import ActionList  # noqa: E402
from wombat.domain.channel import Channel, Layer  # noqa: E402
from wombat.ui.channels_panel import _ROLE_LAYER_IDX, ChannelsPanel  # noqa: E402


def _setup(layer_names: list[str]):
    ch = Channel(name="c", layers=[Layer(actions=ActionList(), name=n) for n in layer_names])
    project = Project.new()
    project.channels.append(ch)
    project.set_active(0)
    player = MagicMock()
    player.frame_time = 1.0 / 30.0
    editor = EditorController(project, player, UndoStack())
    editor.set_active_channel_index(0)
    panel = ChannelsPanel(project, editor=editor)
    return panel, editor, ch


def _layer_items(panel):
    ch_item = panel._tree.topLevelItem(0)
    return [ch_item.child(j) for j in range(ch_item.childCount())]


def test_layers_displayed_top_of_stack_first():
    panel, editor, ch = _setup(["base", "A", "B"])   # model indices 0,1,2
    items = _layer_items(panel)
    # Visual order should be B (idx 2), A (idx 1), base (idx 0)
    assert [it.data(0, _ROLE_LAYER_IDX) for it in items] == [2, 1, 0]
    assert [it.text(0).strip().split()[-1] for it in items] == ["B", "A", "base"]


def test_move_up_increases_model_index():
    panel, editor, ch = _setup(["base", "A", "B"])
    editor.set_active_layer_index(0)   # base
    panel._refresh()
    panel._move_layer_up()             # visually up → toward top of stack
    assert [lay.name for lay in ch.layers] == ["A", "base", "B"]


def test_move_down_decreases_model_index():
    panel, editor, ch = _setup(["base", "A", "B"])
    editor.set_active_layer_index(2)   # B (top of stack)
    panel._refresh()
    panel._move_layer_down()           # visually down → toward base
    assert [lay.name for lay in ch.layers] == ["base", "B", "A"]


def test_button_states_follow_visual_direction():
    panel, editor, ch = _setup(["base", "A", "B"])
    # Select the top-of-stack layer (idx 2): can move down (toward base) but not up.
    editor.set_active_layer_index(2)
    panel._refresh()
    panel._update_button_states()
    assert not panel._btn_layer_up.isEnabled()
    assert panel._btn_layer_down.isEnabled()
    # Select the base (idx 0): can move up but not down.
    editor.set_active_layer_index(0)
    panel._refresh()
    panel._update_button_states()
    assert panel._btn_layer_up.isEnabled()
    assert not panel._btn_layer_down.isEnabled()
