"""Tests for SnippetPanel UI behavior (the 'Use selection' button)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.app.editor import EditorController  # noqa: E402
from wombat.app.project import Project  # noqa: E402
from wombat.app.undo import UndoStack  # noqa: E402
from wombat.domain.action import Action, ActionList  # noqa: E402
from wombat.domain.channel import Channel, Layer  # noqa: E402, I001
from wombat.ui.snippet_panel import SnippetPanel  # noqa: E402


def _panel(*pairs) -> tuple[SnippetPanel, EditorController]:
    al = ActionList(Action(t, p) for t, p in pairs)
    ch = Channel(name="c", layers=[Layer(actions=al)])
    project = Project.new()
    project.channels.append(ch)
    player = MagicMock()
    player.position = 0.0
    editor = EditorController(project, player, UndoStack())
    panel = SnippetPanel(editor, player)
    return panel, editor


def test_use_selection_single_action_sets_start_keeps_duration():
    panel, editor = _panel((1.0, 0), (2.5, 100), (4.0, 0))
    panel._span_dur.setValue(3.0)
    editor.select(2.5)
    panel._use_selection_span()
    assert panel._span_start.value() == pytest.approx(2.5)
    assert panel._span_dur.value() == pytest.approx(3.0)  # unchanged


def test_use_selection_range_sets_start_and_duration():
    panel, editor = _panel((1.0, 0), (2.5, 100), (4.0, 0))
    editor.select(1.0)
    editor.select(4.0, additive=True)
    panel._use_selection_span()
    assert panel._span_start.value() == pytest.approx(1.0)
    assert panel._span_dur.value() == pytest.approx(3.0)


def test_use_selection_empty_falls_back_to_playhead():
    panel, editor = _panel((1.0, 0), (2.5, 100))
    editor.clear_selection()
    panel._player.position = 7.0
    panel._span_dur.setValue(2.0)
    panel._use_selection_span()
    assert panel._span_start.value() == pytest.approx(7.0)
    assert panel._span_dur.value() == pytest.approx(5.0)  # default
