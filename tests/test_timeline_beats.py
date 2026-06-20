"""Tests for the TimelineWidget beat-marker overlay."""
from __future__ import annotations

import sys

import numpy as np
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.audio.beats import BeatGrid  # noqa: E402
from wombat.playback.player import VideoPlayer  # noqa: E402
from wombat.ui.timeline.timeline_widget import TimelineWidget  # noqa: E402


def _timeline() -> TimelineWidget:
    tl = TimelineWidget(VideoPlayer())
    tl.resize(600, 200)
    return tl


def _grid() -> BeatGrid:
    return BeatGrid(
        np.array([0.5, 1.0, 1.5, 2.0], dtype=np.float64),
        np.array([1, 2, 3, 1], dtype=np.int32),
    )


def test_set_beats_stores_grid():
    tl = _timeline()
    g = _grid()
    tl.set_beats(g)
    assert tl._beats is g


def test_beats_visible_default_true_and_toggles():
    tl = _timeline()
    assert tl._show_beats is True
    tl.set_beats_visible(False)
    assert tl._show_beats is False


def test_paint_with_beats_does_not_crash():
    tl = _timeline()
    tl.set_beats(_grid())
    tl.grab()   # forces a paintEvent


def test_paint_with_no_beats_does_not_crash():
    tl = _timeline()
    tl.set_beats(None)
    tl.grab()


def test_paint_with_empty_grid_does_not_crash():
    tl = _timeline()
    tl.set_beats(BeatGrid.empty())
    tl.grab()


def test_paint_hidden_beats_does_not_crash():
    tl = _timeline()
    tl.set_beats(_grid())
    tl.set_beats_visible(False)
    tl.grab()
