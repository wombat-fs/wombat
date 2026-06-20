"""Tests for the DetectedBeats rhythm and its snippet-panel integration."""
from __future__ import annotations

import sys

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from unittest.mock import MagicMock  # noqa: E402

from wombat.audio.beats import BeatGrid  # noqa: E402
from wombat.domain.snippets.base import BeatSnippet  # noqa: E402
from wombat.domain.snippets.positions import Alternate  # noqa: E402
from wombat.domain.snippets.rhythms import DetectedBeats  # noqa: E402


def _grid() -> BeatGrid:
    return BeatGrid(
        np.array([0.5, 1.0, 1.5, 2.0, 2.5], dtype=np.float64),
        np.array([1, 2, 3, 1, 2], dtype=np.int32),
    )


# ------------------------------------------------------------------ rhythm

def test_no_grid_yields_no_beats():
    assert len(DetectedBeats().beats((0.0, 10.0), None)) == 0


def test_empty_grid_yields_no_beats():
    r = DetectedBeats(grid=BeatGrid.empty())
    assert len(r.beats((0.0, 10.0), None)) == 0


def test_returns_beats_in_span():
    r = DetectedBeats(grid=_grid())
    times = r.beats((0.9, 2.1), None)
    assert list(times) == pytest.approx([1.0, 1.5, 2.0])


def test_downbeats_only():
    r = DetectedBeats(downbeats_only=True, grid=_grid())
    times = r.beats((0.0, 10.0), None)
    assert list(times) == pytest.approx([0.5, 2.0])


def test_param_spec_exposes_downbeats_only_not_grid():
    keys = {s.key for s in DetectedBeats.param_specs()}
    assert keys == {"downbeats_only"}


def test_composes_with_pos_algorithm():
    snip = BeatSnippet(rhythm=DetectedBeats(grid=_grid()),
                       pos=Alternate(low=0, high=100))
    actions = snip.generate((0.0, 3.0))
    assert len(actions) == 5
    assert [a.pos for a in actions] == [100, 0, 100, 0, 100]
    assert [a.at for a in actions] == pytest.approx([0.5, 1.0, 1.5, 2.0, 2.5])


# ------------------------------------------------------------------ panel injection

def test_panel_injects_grid_into_detected_beats_snippet():
    from wombat.ui.snippet_panel import SnippetPanel

    editor = MagicMock()
    editor.has_active_channel = True
    panel = SnippetPanel(editor, MagicMock())
    try:
        panel.set_beats(_grid())
        # select the "On Beats" preset (a DetectedBeats rhythm)
        idx = next(i for i in range(panel._preset_combo.count())
                   if panel._preset_combo.itemData(i).name == "On Beats")
        panel._preset_combo.setCurrentIndex(idx)
        snippet = panel._build_snippet()
        assert isinstance(snippet.rhythm, DetectedBeats)
        assert snippet.rhythm.grid is not None
        actions = snippet.generate((0.0, 3.0))
        assert len(actions) == 5
    finally:
        panel.deleteLater()


def test_panel_detected_beats_empty_without_grid():
    from wombat.ui.snippet_panel import SnippetPanel

    editor = MagicMock()
    editor.has_active_channel = True
    panel = SnippetPanel(editor, MagicMock())
    try:
        idx = next(i for i in range(panel._preset_combo.count())
                   if panel._preset_combo.itemData(i).name == "On Beats")
        panel._preset_combo.setCurrentIndex(idx)
        snippet = panel._build_snippet()
        assert isinstance(snippet.rhythm, DetectedBeats)
        assert len(snippet.generate((0.0, 3.0))) == 0   # no grid → no actions
    finally:
        panel.deleteLater()
