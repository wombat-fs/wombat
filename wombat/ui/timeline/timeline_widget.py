"""TimelineWidget — read-only channel-lane canvas with playhead and zoom/pan.

Paint order per frame:
  1. Background fill
  2. Ruler strip (top)
  3. Per-lane: height guides → line segments → action nodes → channel label
  4. Playhead (on top of everything)
"""
from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtCore import QRect, QSize, Qt, Slot
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from wombat.domain.channel import Channel
from wombat.playback.player import VideoPlayer
from wombat.ui.timeline.heatmap import speed_color
from wombat.ui.timeline.viewport import Viewport

# ------------------------------------------------------------------ constants

_RULER_H = 24          # ruler strip height in pixels
_POINT_R = 3           # action node radius

_BG = QColor("#1c1c1c")
_RULER_BG = QColor("#2a2a2a")
_RULER_FG = QColor("#555555")    # tick marks and ruler border
_GUIDE = QColor(255, 255, 255, 18)
_LABEL_FG = QColor("#666666")
_PLAYHEAD_COLOR = QColor("#ffffff")

_LANE_COLORS: list[QColor] = [
    QColor("#00a8e8"),   # blue    — primary
    QColor("#e87d00"),   # orange
    QColor("#00e8a8"),   # teal
    QColor("#e8e800"),   # yellow
    QColor("#e800a8"),   # magenta
]

_DIM = 0.35   # inactive lane brightness multiplier


# ------------------------------------------------------------------ helpers

def _nice_tick_interval(visible_time: float) -> float:
    candidates = [0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0]
    target = visible_time / 7.0
    for c in candidates:
        if c >= target:
            return c
    return candidates[-1]


def _format_time(t: float, visible_time: float) -> str:
    neg = t < 0
    abs_t = abs(t)
    mins = int(abs_t) // 60
    secs = abs_t % 60
    sign = "-" if neg else ""
    if visible_time < 5.0:
        body = f"{mins}:{secs:06.3f}" if mins else f"{secs:.3f}s"
    elif visible_time < 120.0:
        body = f"{mins}:{secs:05.2f}" if mins else f"{secs:.1f}s"
    else:
        body = f"{mins}:{int(secs):02d}"
    return sign + body


def _dim_color(c: QColor, factor: float) -> QColor:
    return QColor(int(c.red() * factor), int(c.green() * factor), int(c.blue() * factor))


# ------------------------------------------------------------------ widget

class TimelineWidget(QWidget):
    def __init__(self, player: VideoPlayer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._player = player
        self._channels: list[Channel] = []
        self._active_index: int = 0
        self._viewport = Viewport(
            offset=0.0,
            visible_time=30.0,
            width=max(1, self.width()),
            lane_top=_RULER_H,
            lane_height=max(1, self.height() - _RULER_H),
        )
        self._playhead_time: float = 0.0
        self._follow: bool = True
        self._follow_fraction: float = 0.5
        self._show_heatmap: bool = False

        self.setMinimumHeight(60)

        player.position_changed.connect(self._on_position)
        player.playback_changed.connect(self._on_playback_changed)

    # ----------------------------------------------------------------- public

    def set_channels(self, channels: list[Channel]) -> None:
        self._channels = list(channels)
        self._active_index = 0
        self.update()

    def set_heatmap(self, enabled: bool) -> None:
        self._show_heatmap = enabled
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(800, 120)

    # ----------------------------------------------------------------- slots

    @Slot(float)
    def _on_position(self, t: float) -> None:
        self._playhead_time = t
        if self._follow:
            offset = t - self._viewport.visible_time * self._follow_fraction
            self._viewport = replace(self._viewport, offset=offset)
        self.update()

    @Slot(bool)
    def _on_playback_changed(self, paused: bool) -> None:
        if not paused:
            self._follow = True

    # ----------------------------------------------------------------- events

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._viewport = replace(
            self._viewport,
            width=max(1, self.width()),
            lane_top=_RULER_H,
            lane_height=max(1, self.height() - _RULER_H),
        )

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 0.85 if delta > 0 else 1.0 / 0.85
            self._viewport = self._viewport.zoom(factor, float(event.position().x()))
        else:
            dt = -(delta / 120.0) * self._viewport.visible_time * 0.2
            self._viewport = self._viewport.pan(dt)
            self._follow = False
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.position().y() < _RULER_H:
            t = self._viewport.x_to_time(float(event.position().x()))
            self._player.seek_exact(t)
        event.accept()

    # ----------------------------------------------------------------- paint

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), _BG)
        self._draw_ruler(painter)

        num = max(1, len(self._channels))
        lane_area_top = _RULER_H
        lane_area_h = max(1, self.height() - _RULER_H)
        per_lane_h = lane_area_h // num

        for i, ch in enumerate(self._channels):
            top = lane_area_top + i * per_lane_h
            # last lane gets any leftover pixels from integer division
            h = per_lane_h if i < num - 1 else lane_area_h - i * per_lane_h
            lane_vp = replace(self._viewport, lane_top=top, lane_height=max(1, h))
            color = _LANE_COLORS[i % len(_LANE_COLORS)]
            self._draw_lane(painter, lane_vp, ch, i == self._active_index, color)

        self._draw_playhead(painter)
        painter.end()

    def _draw_ruler(self, painter: QPainter) -> None:
        painter.fillRect(QRect(0, 0, self.width(), _RULER_H), _RULER_BG)
        painter.setPen(QPen(_RULER_FG, 1))
        painter.drawLine(0, _RULER_H - 1, self.width(), _RULER_H - 1)

        interval = _nice_tick_interval(self._viewport.visible_time)
        t0, t1 = self._viewport.time_window()
        first_tick = math.ceil(t0 / interval) * interval

        fm = painter.fontMetrics()
        t = first_tick
        while t <= t1 + interval * 0.01:
            x = int(self._viewport.time_to_x(t))
            if 0 <= x <= self.width():
                painter.setPen(QPen(_RULER_FG, 1))
                painter.drawLine(x, _RULER_H - 7, x, _RULER_H - 1)
                label = _format_time(t, self._viewport.visible_time)
                lw = fm.horizontalAdvance(label)
                if x + 3 + lw <= self.width():
                    painter.setPen(_LABEL_FG)
                    painter.drawText(x + 3, _RULER_H - 9, label)
            t += interval

    def _draw_lane(
        self,
        painter: QPainter,
        lane_vp: Viewport,
        channel: Channel,
        is_active: bool,
        color: QColor,
    ) -> None:
        actions = channel.synthesize()
        t0, t1 = lane_vp.time_window()

        # horizontal position guides
        painter.setPen(QPen(_GUIDE, 1))
        for guide_pos in (0, 25, 50, 75, 100):
            y = int(lane_vp.pos_to_y(float(guide_pos)))
            painter.drawLine(0, y, self.width(), y)

        if len(actions) == 0:
            painter.setPen(_LABEL_FG)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(4, lane_vp.lane_top + 14, channel.name)
            return

        # cull: index_range gives [lo, hi) within [t0, t1]
        # extend one action each side so edge-crossing segments are drawn
        lo, hi = actions.index_range(t0, t1)
        draw_lo = max(0, lo - 1)
        draw_hi = min(len(actions), hi + 1)
        if draw_hi <= draw_lo:
            painter.setPen(_LABEL_FG)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(4, lane_vp.lane_top + 14, channel.name)
            return

        line_color = color if is_active else _dim_color(color, _DIM)

        xs = [lane_vp.time_to_x(actions[i].at) for i in range(draw_lo, draw_hi)]
        ys = [lane_vp.pos_to_y(float(actions[i].pos)) for i in range(draw_lo, draw_hi)]

        # line segments
        if self._show_heatmap:
            for j in range(len(xs) - 1):
                a1 = actions[draw_lo + j]
                a2 = actions[draw_lo + j + 1]
                dt = a2.at - a1.at
                spd = abs(a2.pos - a1.pos) / dt if dt > 0 else 0.0
                seg_c = speed_color(spd) if is_active else _dim_color(speed_color(spd), _DIM)
                painter.setPen(QPen(seg_c, 2))
                painter.drawLine(int(xs[j]), int(ys[j]), int(xs[j + 1]), int(ys[j + 1]))
        else:
            painter.setPen(QPen(line_color, 2))
            for j in range(len(xs) - 1):
                painter.drawLine(int(xs[j]), int(ys[j]), int(xs[j + 1]), int(ys[j + 1]))

        # action nodes (only the truly visible slice, not the edge extras)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(line_color)
        for i in range(lo, hi):
            x = int(lane_vp.time_to_x(actions[i].at))
            y = int(lane_vp.pos_to_y(float(actions[i].pos)))
            painter.drawEllipse(x - _POINT_R, y - _POINT_R, _POINT_R * 2, _POINT_R * 2)

        # channel name label
        painter.setPen(_LABEL_FG)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(4, lane_vp.lane_top + 14, channel.name)

    def _draw_playhead(self, painter: QPainter) -> None:
        x = int(self._viewport.time_to_x(self._playhead_time))
        if 0 <= x <= self.width():
            painter.setPen(QPen(_PLAYHEAD_COLOR, 1))
            painter.drawLine(x, 0, x, self.height())
