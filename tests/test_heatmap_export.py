"""Tests for the standalone heatmap image renderer."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.domain.action import Action, ActionList  # noqa: E402
from wombat.domain.chapter import Chapter  # noqa: E402
from wombat.ui.heatmap_export import render_heatmap  # noqa: E402
from wombat.ui.timeline.heatmap import speed_color  # noqa: E402


def _actions(*pairs) -> ActionList:
    return ActionList(Action(t, p) for t, p in pairs)


def test_render_returns_image_of_expected_size():
    al = _actions((0.0, 0), (1.0, 100), (2.0, 0))
    img = render_heatmap(al, duration=2.0, width=400, height=50)
    assert img.width() == 400
    assert img.height() == 50


def test_chapter_strip_adds_height():
    al = _actions((0.0, 0), (1.0, 100))
    chapters = [Chapter(at=0.5, name="intro")]
    img = render_heatmap(al, duration=1.0, width=200, height=40, chapters=chapters)
    assert img.height() > 40  # strip appended below the heatmap


def test_segment_color_matches_speed():
    # A fast stroke (0→100 in 0.5s = 200 u/s) should paint the fast color.
    al = _actions((0.0, 0), (0.5, 100))
    img = render_heatmap(al, duration=0.5, width=100, height=10)
    expected = speed_color(200.0).rgb()
    # Sample a pixel inside the single segment.
    assert img.pixel(50, 5) == expected


def test_empty_actions_is_background_only():
    img = render_heatmap(ActionList(), duration=5.0, width=100, height=10)
    assert img.width() == 100
    # No crash, uniform background — top-left equals bottom-right.
    assert img.pixel(0, 0) == img.pixel(99, 9)


def test_zero_duration_does_not_crash():
    al = _actions((0.0, 0), (1.0, 100))
    img = render_heatmap(al, duration=0.0, width=100, height=10)
    assert img.width() == 100
