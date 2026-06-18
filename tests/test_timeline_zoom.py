"""Tests for TimelineWidget zoom-level API and the ZoomControl strip."""
from __future__ import annotations

import sys

import pytest

# QApplication required for QWidget construction.
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.playback.player import VideoPlayer  # noqa: E402
from wombat.ui.timeline.timeline_widget import TimelineWidget  # noqa: E402
from wombat.ui.timeline.zoom_control import ZoomControl  # noqa: E402


def _timeline() -> TimelineWidget:
    tl = TimelineWidget(VideoPlayer())
    tl.resize(600, 200)
    return tl


# ------------------------------------------------------------------ zoom level

def test_default_zoom_is_one():
    assert _timeline().zoom_level() == pytest.approx(1.0)


def test_set_zoom_level_shrinks_visible_time():
    tl = _timeline()
    tl.set_zoom_level(2.0)
    assert tl._viewport.visible_time == pytest.approx(TimelineWidget.BASE_VISIBLE / 2.0)
    assert tl.zoom_level() == pytest.approx(2.0)


def test_zoom_by_multiplies_level():
    tl = _timeline()
    tl.set_zoom_level(2.0)
    tl.zoom_by(2.0)
    assert tl.zoom_level() == pytest.approx(4.0)


def test_set_zoom_clamps_to_max():
    tl = _timeline()
    tl.set_zoom_level(10_000.0)
    assert tl.zoom_level() == pytest.approx(tl.max_zoom_level())


def test_set_zoom_clamps_to_min():
    tl = _timeline()
    tl.set_zoom_level(0.0001)
    assert tl.zoom_level() == pytest.approx(tl.min_zoom_level())


def test_zoom_changed_signal_emitted():
    tl = _timeline()
    seen: list[float] = []
    tl.zoom_changed.connect(seen.append)
    tl.set_zoom_level(3.0)
    assert seen and seen[-1] == pytest.approx(3.0)


# ------------------------------------------------------------------ control

def test_control_reflects_initial_level():
    tl = _timeline()
    zc = ZoomControl(tl)
    assert zc._combo.currentText() == "1×"


def test_control_updates_on_zoom_change():
    tl = _timeline()
    zc = ZoomControl(tl)
    tl.set_zoom_level(2.0)
    assert zc._combo.currentText() == "2×"


def test_control_typed_value_sets_zoom():
    tl = _timeline()
    zc = ZoomControl(tl)
    zc._combo.lineEdit().setText("4x")
    zc._on_text_entered()
    assert tl.zoom_level() == pytest.approx(4.0)


def test_control_invalid_text_reverts():
    tl = _timeline()
    zc = ZoomControl(tl)
    tl.set_zoom_level(2.0)
    zc._combo.lineEdit().setText("nonsense")
    zc._on_text_entered()
    assert tl.zoom_level() == pytest.approx(2.0)
    assert zc._combo.currentText() == "2×"
