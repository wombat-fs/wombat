"""TimelineWidget — channel-lane canvas with playhead, zoom/pan, and editing.

Paint order per frame:
  1. Background fill
  2. Ruler strip (top)
  3. Per-lane: height guides → line segments → action nodes → channel label
  4. Rubber-band rectangle (if dragging)
  5. Playhead (on top of everything)

Mouse interactions (requires EditorController via set_editor()):
  Left-click empty lane  → ScriptingMode.add_point
  Left-drag empty area   → rubber-band select (moves > _DRAG_THRESHOLD px)
  Left-click action node → select (Shift/Ctrl = additive)
  Left-drag action node  → move selection as one undo step
  Ruler click            → seek
"""
from __future__ import annotations

import math
from dataclasses import replace
from enum import Enum, auto
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Slot
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from wombat.domain.action import Action
from wombat.domain.channel import Channel
from wombat.playback.player import VideoPlayer
from wombat.ui.timeline.heatmap import speed_color
from wombat.ui.timeline.viewport import Viewport

if TYPE_CHECKING:
    from wombat.app.editor import EditorController
    from wombat.ui.scripting.mode import ScriptingMode

# ------------------------------------------------------------------ constants

_RULER_H = 24
_POINT_R = 3
_SEL_R = 5            # selected node radius
_DRAG_THRESHOLD = 4   # pixels before a press becomes a rubber-band drag

_BG = QColor("#1c1c1c")
_RULER_BG = QColor("#2a2a2a")
_RULER_FG = QColor("#555555")
_GUIDE = QColor(255, 255, 255, 18)
_LABEL_FG = QColor("#666666")
_PLAYHEAD_COLOR = QColor("#ffffff")
_SEL_COLOR = QColor("#ffffff")
_RUBBER_BAND_FILL = QColor(255, 255, 255, 20)
_RUBBER_BAND_BORDER = QColor(255, 255, 255, 120)

_LANE_COLORS: list[QColor] = [
    QColor("#00a8e8"),
    QColor("#e87d00"),
    QColor("#00e8a8"),
    QColor("#e8e800"),
    QColor("#e800a8"),
]

_DIM = 0.35


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


# ------------------------------------------------------------------ drag state

class _DragMode(Enum):
    NONE = auto()
    PENDING = auto()      # pressed on empty area; waiting to see click vs drag
    RUBBER_BAND = auto()
    MOVE = auto()


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

        # editing state
        self._editor: EditorController | None = None
        self._scripting_mode: ScriptingMode
        from wombat.ui.scripting.mode import DefaultMode
        self._scripting_mode = DefaultMode()
        self._drag_mode: _DragMode = _DragMode.NONE
        self._drag_start: QPointF = QPointF()
        self._drag_current: QPointF = QPointF()
        # for move gesture: total delta is computed vs press position
        self._move_press_t: float = 0.0
        self._move_press_p: float = 0.0

        self.setMinimumHeight(60)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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

    def set_editor(self, editor: EditorController) -> None:
        if self._editor is not None:
            self._editor.actions_changed.disconnect(self.update)
            self._editor.selection_changed.disconnect(self.update)
        self._editor = editor
        editor.actions_changed.connect(self.update)
        editor.selection_changed.connect(self.update)

    def set_scripting_mode(self, mode: ScriptingMode) -> None:
        self._scripting_mode = mode

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
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return

        x = float(event.position().x())
        y = float(event.position().y())

        # Ruler → seek
        if y < _RULER_H:
            t = self._viewport.x_to_time(x)
            self._player.seek_exact(t)
            event.accept()
            return

        if self._editor is None or not self._editor.has_active_channel:
            event.accept()
            return

        lane_vp = self._active_lane_vp()
        t = lane_vp.x_to_time(x)
        p_at_y = lane_vp.y_to_pos(y)

        hit = self._hit_test(t, lane_vp)
        additive = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
        )

        if hit is not None:
            # Select + start move drag
            if hit.at not in self._editor.selection or not additive:
                self._editor.select(hit.at, additive=additive)
            self._drag_mode = _DragMode.MOVE
            self._drag_start = event.position()
            self._drag_current = event.position()
            self._move_press_t = t
            self._move_press_p = p_at_y
            self._editor.begin_move()
        else:
            # Empty lane press — pending (click = add, drag = rubber-band)
            self._drag_mode = _DragMode.PENDING
            self._drag_start = event.position()
            self._drag_current = event.position()

        self._follow = False
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode == _DragMode.NONE:
            return

        self._drag_current = event.position()
        dx = self._drag_current.x() - self._drag_start.x()
        dy = self._drag_current.y() - self._drag_start.y()

        if self._drag_mode == _DragMode.PENDING:
            dist = math.hypot(dx, dy)
            if dist >= _DRAG_THRESHOLD:
                self._drag_mode = _DragMode.RUBBER_BAND

        elif self._drag_mode == _DragMode.RUBBER_BAND:
            self.update()

        elif self._drag_mode == _DragMode.MOVE:
            if self._editor is not None:
                lane_vp = self._active_lane_vp()
                dt = dx / lane_vp.width * lane_vp.visible_time if lane_vp.width else 0.0
                dp = int(-dy / lane_vp.lane_height * 100.0) if lane_vp.lane_height else 0
                self._editor.move_selection(dt, dp)
            self.update()

        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return

        mode = self._drag_mode
        self._drag_mode = _DragMode.NONE

        if mode == _DragMode.PENDING:
            # No significant movement → add point
            if self._editor is not None and self._editor.has_active_channel:
                lane_vp = self._active_lane_vp()
                x = float(self._drag_start.x())
                y = float(self._drag_start.y())
                t = lane_vp.x_to_time(x)
                pos = int(round(max(0.0, min(100.0, lane_vp.y_to_pos(y)))))
                self._scripting_mode.add_point(self._editor, t, pos)

        elif mode == _DragMode.RUBBER_BAND:
            if self._editor is not None:
                lane_vp = self._active_lane_vp()
                x0 = min(self._drag_start.x(), self._drag_current.x())
                x1 = max(self._drag_start.x(), self._drag_current.x())
                t0 = lane_vp.x_to_time(float(x0))
                t1 = lane_vp.x_to_time(float(x1))
                additive = bool(
                    event.modifiers()
                    & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
                )
                self._editor.select_time_range(t0, t1, additive=additive)
            self.update()

        elif mode == _DragMode.MOVE:
            if self._editor is not None:
                self._editor.end_move()

        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._editor is None:
            super().keyPressEvent(event)
            return

        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._editor.remove_selection()
            event.accept()
        elif ctrl and key == Qt.Key.Key_Z:
            self._editor.undo()
            event.accept()
        elif ctrl and key == Qt.Key.Key_Y:
            self._editor.redo()
            event.accept()
        elif ctrl and key == Qt.Key.Key_C:
            self._editor.copy()
            event.accept()
        elif ctrl and key == Qt.Key.Key_X:
            self._editor.cut()
            event.accept()
        elif ctrl and shift and key == Qt.Key.Key_V:
            self._editor.paste_exact()
            event.accept()
        elif ctrl and key == Qt.Key.Key_V:
            self._editor.paste(self._player.logical_time)
            event.accept()
        elif ctrl and key == Qt.Key.Key_A:
            self._editor.select_all()
            event.accept()
        elif key == Qt.Key.Key_P:
            # Add point at playhead with pos 50 (keyboard authoring shortcut)
            if self._editor.has_active_channel:
                self._scripting_mode.add_point(self._editor, self._player.logical_time, 50)
            event.accept()
        else:
            super().keyPressEvent(event)

    # ----------------------------------------------------------------- helpers

    def _active_lane_vp(self) -> Viewport:
        """Viewport for the active channel's lane (Phase 4: single lane = full area)."""
        n = max(1, len(self._channels))
        lane_area_top = _RULER_H
        lane_area_h = max(1, self.height() - _RULER_H)
        per_lane_h = lane_area_h // n
        i = self._editor._active_idx if self._editor is not None else 0
        i = max(0, min(n - 1, i))
        top = lane_area_top + i * per_lane_h
        h = per_lane_h if i < n - 1 else lane_area_h - i * per_lane_h
        return replace(self._viewport, lane_top=top, lane_height=max(1, h))

    def _hit_test(self, t: float, lane_vp: Viewport) -> Action | None:
        if not self._editor or not self._editor.has_active_channel:
            return None
        actions = self._editor.active_channel.synthesize()
        if not actions or lane_vp.width == 0:
            return None
        tol = (_POINT_R + 3) / lane_vp.width * lane_vp.visible_time
        return actions.at_time(t, tol)

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

        sel = self._editor.selection if self._editor is not None else frozenset()

        for i, ch in enumerate(self._channels):
            top = lane_area_top + i * per_lane_h
            h = per_lane_h if i < num - 1 else lane_area_h - i * per_lane_h
            lane_vp = replace(self._viewport, lane_top=top, lane_height=max(1, h))
            color = _LANE_COLORS[i % len(_LANE_COLORS)]
            self._draw_lane(painter, lane_vp, ch, i == self._active_index, color, sel)

        if self._drag_mode == _DragMode.RUBBER_BAND:
            self._draw_rubber_band(painter)

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
        selection: frozenset[float],
    ) -> None:
        actions = channel.synthesize()
        t0, t1 = lane_vp.time_window()

        painter.setPen(QPen(_GUIDE, 1))
        for guide_pos in (0, 25, 50, 75, 100):
            y = int(lane_vp.pos_to_y(float(guide_pos)))
            painter.drawLine(0, y, self.width(), y)

        if len(actions) == 0:
            painter.setPen(_LABEL_FG)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(4, lane_vp.lane_top + 14, channel.name)
            return

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

        # Nodes: selected ones drawn larger and white; others normal
        for i in range(lo, hi):
            a = actions[i]
            x = int(lane_vp.time_to_x(a.at))
            y = int(lane_vp.pos_to_y(float(a.pos)))
            if a.at in selection:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_SEL_COLOR)
                painter.drawEllipse(x - _SEL_R, y - _SEL_R, _SEL_R * 2, _SEL_R * 2)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(line_color)
                painter.drawEllipse(x - _POINT_R, y - _POINT_R, _POINT_R * 2, _POINT_R * 2)

        painter.setPen(_LABEL_FG)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(4, lane_vp.lane_top + 14, channel.name)

    def _draw_rubber_band(self, painter: QPainter) -> None:
        x0 = min(self._drag_start.x(), self._drag_current.x())
        y0 = min(self._drag_start.y(), self._drag_current.y())
        x1 = max(self._drag_start.x(), self._drag_current.x())
        y1 = max(self._drag_start.y(), self._drag_current.y())
        rect = QRectF(x0, y0, x1 - x0, y1 - y0)
        painter.fillRect(rect, _RUBBER_BAND_FILL)
        painter.setPen(QPen(_RUBBER_BAND_BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

    def _draw_playhead(self, painter: QPainter) -> None:
        x = int(self._viewport.time_to_x(self._playhead_time))
        if 0 <= x <= self.width():
            painter.setPen(QPen(_PLAYHEAD_COLOR, 1))
            painter.drawLine(x, 0, x, self.height())
