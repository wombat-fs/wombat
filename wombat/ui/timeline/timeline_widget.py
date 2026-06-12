"""TimelineWidget — channel-lane canvas with playhead, zoom/pan, and editing.

Paint order per frame:
  1. Background fill
  2. Ruler strip (top)
  3. Per-lane: height guides → line segments → action nodes → channel label
  4. Active-lane border (subtle highlight)
  5. Rubber-band rectangle (if dragging)
  6. Playhead (on top of everything)

Mouse interactions (requires EditorController via set_editor()):
  Left-click inactive lane → activate that channel (no edit)
  Left-click empty lane   → ScriptingMode.add_point
  Left-drag empty area    → rubber-band select (moves > _DRAG_THRESHOLD px)
  Left-click action node  → select (Shift/Ctrl = additive)
  Left-drag action node   → move selection as one undo step
  Ruler click             → seek
  Click expand toggle     → expand/collapse channel to show layer sub-lanes
  Drag span edge          → resize layer span
  Drag fade handle        → adjust layer fade-in or fade-out
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import TYPE_CHECKING

import numpy as np

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
    from wombat.app.project import Project
    from wombat.ui.scripting.mode import ScriptingMode

# ------------------------------------------------------------------ constants

_RULER_H = 24
_POINT_R = 3
_SEL_R = 5
_DRAG_THRESHOLD = 4       # px before press becomes rubber-band
_HANDLE_TOL = 8           # px hit tolerance for span/fade handles
_EXPAND_BTN_W = 16        # width of the ▶/▼ expand button zone
_INACTIVE_LANE_H = 28     # fixed px height for non-active channel lanes

_BG = QColor("#1c1c1c")
_RULER_BG = QColor("#2a2a2a")
_RULER_FG = QColor("#666666")
_GUIDE = QColor(255, 255, 255, 18)
_LABEL_FG = QColor("#bbbbbb")
_PLAYHEAD_COLOR = QColor("#ffffff")
_SEL_COLOR = QColor("#ffffff")
_RUBBER_BAND_FILL = QColor(255, 255, 255, 20)
_RUBBER_BAND_BORDER = QColor(255, 255, 255, 120)
_ACTIVE_BORDER = QColor(255, 255, 255, 40)
_GRID_LINE = QColor(255, 255, 255, 14)
_T0_LINE = QColor(255, 255, 255, 90)
_SUBLANE_BG = QColor(255, 255, 255, 6)
_SPAN_FILL = QColor(255, 255, 255, 22)
_SPAN_BORDER = QColor(255, 255, 255, 70)
_FADE_HANDLE = QColor(255, 200, 80, 200)
_GHOST_ALPHA = 0.18
_CHAPTER_COLOR = QColor(240, 192, 48, 220)   # gold, slightly transparent

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


def _alpha_color(c: QColor, alpha: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(alpha)
    return out


# ------------------------------------------------------------------ lane geometry

@dataclass
class _LaneInfo:
    ch_idx: int
    layer_idx: int   # -1 = channel composite summary lane
    top: int
    height: int

    @property
    def is_channel(self) -> bool:
        return self.layer_idx == -1

    @property
    def bottom(self) -> int:
        return self.top + self.height


# ------------------------------------------------------------------ drag state

class _DragMode(Enum):
    NONE = auto()
    PENDING = auto()
    RUBBER_BAND = auto()
    MOVE = auto()
    SPAN_START = auto()   # dragging layer span left edge
    SPAN_END = auto()     # dragging layer span right edge
    FADE_IN = auto()      # dragging fade-in handle
    FADE_OUT = auto()     # dragging fade-out handle
    CHAPTER = auto()      # dragging a chapter marker


# ------------------------------------------------------------------ widget

class TimelineWidget(QWidget):
    def __init__(self, player: VideoPlayer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._player = player
        self._channels: list[Channel] = []
        self._active_index: int = 0
        self._project: Project | None = None
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
        self._show_waveform: bool = True
        self._waveform = None   # WaveformData | None

        # editing state
        self._editor: EditorController | None = None
        self._scripting_mode: ScriptingMode
        from wombat.ui.scripting.mode import DefaultMode
        self._scripting_mode = DefaultMode()
        self._drag_mode: _DragMode = _DragMode.NONE
        self._drag_start: QPointF = QPointF()
        self._drag_current: QPointF = QPointF()
        self._move_press_t: float = 0.0
        self._move_press_p: float = 0.0
        # for chapter drags:
        self._drag_chapter = None          # Chapter | None
        # for span/fade drags:
        self._drag_target_layer: int = 0   # layer_idx being dragged
        self._drag_span_anchor: float = 0.0  # the fixed edge of the span
        self._drag_initial_fade: float = 0.0

        # expand/collapse state
        self._expanded_channels: set[int] = set()

        # paint caches
        self._lanes_cache: list[_LaneInfo] | None = None
        # (obj_id, act_len, lane_top, lane_height) -> np.ndarray of y pixels
        self._ys_cache: dict = {}
        # (obj_id, act_len) -> np.ndarray of at values
        self._at_cache: dict = {}
        # (lane_height,) -> (QPixmap, pre_t0, pre_t1, visible_time, width)
        self._waveform_pixmap_cache: dict = {}

        self.setMinimumHeight(60)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        player.position_changed.connect(self._on_position)
        player.playback_changed.connect(self._on_playback_changed)

    # ----------------------------------------------------------------- public

    def set_channels(self, channels: list[Channel]) -> None:
        self._channels = list(channels)
        self._active_index = 0
        self._invalidate_lanes()
        self.update()

    def set_heatmap(self, enabled: bool) -> None:
        self._show_heatmap = enabled
        self.update()

    def set_waveform(self, data) -> None:
        """Set waveform data (WaveformData or None) and repaint."""
        self._waveform = data
        self._waveform_pixmap_cache.clear()
        self.update()

    def set_waveform_visible(self, visible: bool) -> None:
        self._show_waveform = visible
        self.update()

    def set_editor(self, editor: EditorController) -> None:
        if self._editor is not None:
            self._editor.actions_changed.disconnect(self._invalidate_coords)
            self._editor.actions_changed.disconnect(self.update)
            self._editor.selection_changed.disconnect(self.update)
            try:
                self._editor.layer_structure_changed.disconnect(self._invalidate_lanes)
                self._editor.layer_structure_changed.disconnect(self.update)
            except RuntimeError:
                pass
        self._editor = editor
        editor.actions_changed.connect(self._invalidate_coords)
        editor.actions_changed.connect(self.update)
        editor.selection_changed.connect(self.update)
        editor.layer_structure_changed.connect(self._invalidate_lanes)
        editor.layer_structure_changed.connect(self.update)

    def set_project(self, project: Project) -> None:
        if self._project is not None:
            try:
                self._project.channels_changed.disconnect(self._on_channels_changed)
                self._project.active_changed.disconnect(self._on_active_changed)
                self._project.chapters_changed.disconnect(self.update)
            except RuntimeError:
                pass
        self._project = project
        self._channels = list(project.channels)
        self._active_index = project.active_index
        project.channels_changed.connect(self._on_channels_changed)
        project.active_changed.connect(self._on_active_changed)
        project.chapters_changed.connect(self.update)
        self.update()

    def set_scripting_mode(self, mode: ScriptingMode) -> None:
        self._scripting_mode = mode

    def get_view_state(self) -> tuple[float, float]:
        return self._viewport.offset, self._viewport.visible_time

    def restore_view_state(self, offset: float, visible_time: float) -> None:
        self._viewport = replace(self._viewport, offset=offset, visible_time=visible_time)
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

    @Slot()
    def _on_channels_changed(self) -> None:
        if self._project is not None:
            self._channels = list(self._project.channels)
            self._active_index = self._project.active_index
        self._invalidate_lanes()
        self.update()

    @Slot(int)
    def _on_active_changed(self, index: int) -> None:
        self._active_index = index
        self._invalidate_lanes()
        self.update()

    # ----------------------------------------------------------------- events

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._viewport = replace(
            self._viewport,
            width=max(1, self.width()),
            lane_top=_RULER_H,
            lane_height=max(1, self.height() - _RULER_H),
        )
        self._invalidate_lanes()

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

        # Ruler → drag chapter marker or seek
        if y < _RULER_H:
            t = self._viewport.x_to_time(x)
            near = self._chapter_near(t)
            if near is not None:
                self._drag_mode = _DragMode.CHAPTER
                self._drag_chapter = near
                self._drag_start = event.position()
                self._drag_current = event.position()
                self._follow = False
            else:
                self._player.seek_exact(t)
            event.accept()
            return

        lanes = self._compute_lanes()
        lane = self._lane_at(x, y, lanes)
        if lane is None:
            event.accept()
            return

        # Expand/collapse toggle in channel summary lane
        if lane.is_channel and x <= _EXPAND_BTN_W + 4:
            self._toggle_expand(lane.ch_idx)
            event.accept()
            return

        # Activate channel on click
        if lane.ch_idx != self._active_index and self._project is not None:
            self._project.set_active(lane.ch_idx)
            self._follow = False
            # Also set active layer if clicking a layer sub-lane
            if not lane.is_channel and self._editor is not None:
                self._editor.set_active_layer_index(lane.layer_idx)
            event.accept()
            return

        # Layer sub-lane interactions
        if not lane.is_channel and self._editor is not None:
            if lane.layer_idx != self._editor.active_layer_index:
                self._editor.set_active_layer_index(lane.layer_idx)

            ch = self._channels[lane.ch_idx]
            li = lane.layer_idx
            if 0 <= li < len(ch.layers):
                layer = ch.layers[li]
                lane_vp = self._lane_viewport(lane)
                t = lane_vp.x_to_time(x)

                # Check for span/fade handle hits
                handle = self._hit_span_handle(x, layer, lane_vp)
                if handle is not None:
                    assert layer.span is not None
                    if handle == "span_start":
                        self._editor.begin_span_drag(li)
                        self._drag_mode = _DragMode.SPAN_START
                        self._drag_span_anchor = layer.span[1]
                    elif handle == "span_end":
                        self._editor.begin_span_drag(li)
                        self._drag_mode = _DragMode.SPAN_END
                        self._drag_span_anchor = layer.span[0]
                    elif handle == "fade_in":
                        self._editor.begin_fade_drag(li)
                        self._drag_mode = _DragMode.FADE_IN
                        self._drag_initial_fade = layer.fade_in
                        self._drag_span_anchor = layer.span[0]  # span start
                    elif handle == "fade_out":
                        self._editor.begin_fade_drag(li)
                        self._drag_mode = _DragMode.FADE_OUT
                        self._drag_initial_fade = layer.fade_out
                        self._drag_span_anchor = layer.span[1]  # span end
                    self._drag_target_layer = li
                    self._drag_start = event.position()
                    self._drag_current = event.position()
                    self._follow = False
                    event.accept()
                    return

        if self._editor is None or not self._editor.has_active_channel:
            event.accept()
            return

        active_lane = self._active_lane(lanes)
        if active_lane is None:
            event.accept()
            return

        lane_vp = self._lane_viewport(active_lane)
        t = lane_vp.x_to_time(x)
        p_at_y = lane_vp.y_to_pos(y)

        hit = self._hit_test(t, lane_vp)
        additive = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
        )

        if hit is not None:
            if hit.at not in self._editor.selection or not additive:
                self._editor.select(hit.at, additive=additive)
            self._drag_mode = _DragMode.MOVE
            self._drag_start = event.position()
            self._drag_current = event.position()
            self._move_press_t = t
            self._move_press_p = p_at_y
            self._editor.begin_move()
        else:
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
            if math.hypot(dx, dy) >= _DRAG_THRESHOLD:
                self._drag_mode = _DragMode.RUBBER_BAND

        elif self._drag_mode == _DragMode.RUBBER_BAND:
            self.update()

        elif self._drag_mode == _DragMode.MOVE:
            if self._editor is not None:
                lanes = self._compute_lanes()
                al = self._active_lane(lanes)
                if al is not None:
                    lane_vp = self._lane_viewport(al)
                    dt = dx / lane_vp.width * lane_vp.visible_time if lane_vp.width else 0.0
                    dp = int(-dy / lane_vp.lane_height * 100.0) if lane_vp.lane_height else 0
                    self._editor.move_selection(dt, dp)
            self.update()

        elif self._drag_mode in (_DragMode.SPAN_START, _DragMode.SPAN_END):
            if self._editor is not None:
                t = self._viewport.x_to_time(float(self._drag_current.x()))
                li = self._drag_target_layer
                ch = self._editor.active_channel
                if 0 <= li < len(ch.layers):
                    layer = ch.layers[li]
                    if layer.span is not None:
                        if self._drag_mode == _DragMode.SPAN_START:
                            new_start = min(t, self._drag_span_anchor - 0.001)
                            self._editor.update_span_live(li, (new_start, self._drag_span_anchor))
                        else:
                            new_end = max(t, self._drag_span_anchor + 0.001)
                            self._editor.update_span_live(li, (self._drag_span_anchor, new_end))
            self.update()

        elif self._drag_mode in (_DragMode.FADE_IN, _DragMode.FADE_OUT):
            if self._editor is not None:
                t = self._viewport.x_to_time(float(self._drag_current.x()))
                li = self._drag_target_layer
                ch = self._editor.active_channel
                if 0 <= li < len(ch.layers):
                    layer = ch.layers[li]
                    if layer.span is not None:
                        if self._drag_mode == _DragMode.FADE_IN:
                            new_fi = max(0.0, t - self._drag_span_anchor)
                            self._editor.update_fades_live(li, new_fi, layer.fade_out)
                        else:
                            new_fo = max(0.0, self._drag_span_anchor - t)
                            self._editor.update_fades_live(li, layer.fade_in, new_fo)
            self.update()

        elif self._drag_mode == _DragMode.CHAPTER:
            if self._drag_chapter is not None and self._project is not None:
                t = max(0.0, self._viewport.x_to_time(float(self._drag_current.x())))
                self._project.move_chapter(self._drag_chapter, t)

        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return

        mode = self._drag_mode
        self._drag_mode = _DragMode.NONE

        if mode == _DragMode.PENDING:
            if self._editor is not None and self._editor.has_active_channel:
                lanes = self._compute_lanes()
                al = self._active_lane(lanes)
                if al is not None:
                    lane_vp = self._lane_viewport(al)
                    x = float(self._drag_start.x())
                    y = float(self._drag_start.y())
                    t = lane_vp.x_to_time(x)
                    pos = int(round(max(0.0, min(100.0, lane_vp.y_to_pos(y)))))
                    self._scripting_mode.add_point(self._editor, t, pos)

        elif mode == _DragMode.RUBBER_BAND:
            if self._editor is not None:
                lanes = self._compute_lanes()
                al = self._active_lane(lanes)
                if al is not None:
                    lane_vp = self._lane_viewport(al)
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

        elif mode in (_DragMode.SPAN_START, _DragMode.SPAN_END):
            if self._editor is not None:
                self._editor.end_span_drag()

        elif mode in (_DragMode.FADE_IN, _DragMode.FADE_OUT):
            if self._editor is not None:
                self._editor.end_fade_drag()

        elif mode == _DragMode.CHAPTER:
            if self._drag_chapter is not None and self._project is not None:
                t = max(0.0, self._viewport.x_to_time(float(self._drag_current.x())))
                self._project.move_chapter(self._drag_chapter, t)
            self._drag_chapter = None

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
            if self._editor.has_active_channel:
                self._scripting_mode.add_point(self._editor, self._player.logical_time, 50)
            event.accept()
        elif key == Qt.Key.Key_Right and not ctrl and not shift:
            self._navigate_to_adjacent_action(forward=True)
            event.accept()
        elif key == Qt.Key.Key_Left and not ctrl and not shift:
            self._navigate_to_adjacent_action(forward=False)
            event.accept()
        else:
            super().keyPressEvent(event)

    def _navigate_to_adjacent_action(self, forward: bool) -> None:
        if not self._channels or self._active_index >= len(self._channels):
            return
        actions = self._channels[self._active_index].synthesize()
        if not actions:
            return
        t = self._player.logical_time
        # Use one full frame as the proximity threshold so that landing slightly
        # off a pos (due to frame-rate rounding) still counts as "at" that pos.
        frame_t = self._player.frame_time or (1.0 / 30.0)
        if forward:
            target = next((a.at for a in actions if a.at > t + frame_t), None)
        else:
            target = next((a.at for a in reversed(list(actions)) if a.at < t - frame_t), None)
        if target is not None:
            self._follow = True
            self._player.seek_exact(target)
            if self._editor is not None:
                self._editor.select(target, additive=False)

    def contextMenuEvent(self, event) -> None:
        y = event.pos().y()
        if y < _RULER_H and self._project is not None:
            from PySide6.QtWidgets import QMenu, QInputDialog
            t = self._viewport.x_to_time(float(event.pos().x()))
            t_label = _format_time(t, self._viewport.visible_time)
            menu = QMenu(self)
            add_act = menu.addAction(f"Add Chapter at {t_label}")
            # Show delete option if there is a nearby chapter
            near = self._chapter_near(t)
            del_act = menu.addAction(f"Remove '{near.name or t_label}'") if near else None
            chosen = menu.exec(event.globalPos())
            if chosen is add_act:
                name, ok = QInputDialog.getText(self, "Add Chapter", "Chapter name (optional):")
                if ok:
                    self._project.add_chapter(t, name=name.strip())
            elif del_act is not None and chosen is del_act and near is not None:
                self._project.remove_chapter(near)
        else:
            super().contextMenuEvent(event)

    def _chapter_near(self, t: float, tol_px: float = 8.0):
        """Return a chapter within tol pixels of t, or None."""
        if self._project is None:
            return None
        tol_t = tol_px / self._viewport.width * self._viewport.visible_time if self._viewport.width else 0.01
        for ch in self._project.chapters:
            if abs(ch.at - t) <= tol_t:
                return ch
        return None

    # ----------------------------------------------------------------- cache invalidation

    def _invalidate_lanes(self) -> None:
        self._lanes_cache = None
        self._ys_cache.clear()
        self._at_cache.clear()
        self._waveform_pixmap_cache.clear()

    def _invalidate_coords(self) -> None:
        self._ys_cache.clear()
        self._at_cache.clear()

    def _get_coords(
        self,
        actions,
        draw_lo: int,
        draw_hi: int,
        lane_vp: Viewport,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (xs, ys) pixel arrays for actions[draw_lo:draw_hi].

        ys are cached per (object-id, length, lane geometry) — stable during
        playback since pos values and lane heights don't change.
        xs are recomputed each call via vectorized numpy since the viewport
        offset scrolls every frame in follow mode.
        """
        obj_id = id(actions)
        act_len = len(actions)

        at_key = (obj_id, act_len)
        if at_key not in self._at_cache:
            self._at_cache[at_key] = np.array([a.at for a in actions], dtype=np.float64)
        at_arr = self._at_cache[at_key]

        ys_key = (obj_id, act_len, lane_vp.lane_top, lane_vp.lane_height)
        if ys_key not in self._ys_cache:
            pos_arr = np.array([a.pos for a in actions], dtype=np.float64)
            # Mirrors Viewport.pos_to_y: lane_top + (1 - pos/100) * lane_height
            self._ys_cache[ys_key] = (
                lane_vp.lane_top + lane_vp.lane_height
                - pos_arr * (lane_vp.lane_height / 100.0)
            )
        ys_full = self._ys_cache[ys_key]

        at_slice = at_arr[draw_lo:draw_hi]
        xs = (at_slice - lane_vp.offset) / lane_vp.visible_time * lane_vp.width
        return xs, ys_full[draw_lo:draw_hi]

    # ----------------------------------------------------------------- lane geometry

    def _compute_lanes(self) -> list[_LaneInfo]:
        """Build the list of logical lanes with pixel bounds.

        The active channel expands to fill remaining space; inactive channels
        get a fixed small height so 7+ channels stay usable simultaneously.
        """
        if self._lanes_cache is not None:
            return self._lanes_cache

        lane_area_top = _RULER_H
        lane_area_h = max(1, self.height() - _RULER_H)

        if not self._channels:
            return [_LaneInfo(ch_idx=0, layer_idx=-1, top=lane_area_top, height=lane_area_h)]

        active = self._active_index

        # Compute total height consumed by inactive channels (including their sublanes)
        inactive_total = 0
        for ci, ch in enumerate(self._channels):
            if ci == active:
                continue
            n_sublanes = (max(1, len(ch.layers)) if ci in self._expanded_channels else 0)
            inactive_total += _INACTIVE_LANE_H * (1 + n_sublanes)

        # Active channel gets whatever is left, divided evenly over its units
        active_units = 1
        if active in self._expanded_channels and active < len(self._channels):
            active_units += max(1, len(self._channels[active].layers))
        active_total = max(_INACTIVE_LANE_H * active_units, lane_area_h - inactive_total)
        active_unit_h = active_total // active_units

        lanes: list[_LaneInfo] = []
        y = lane_area_top
        for ci, ch in enumerate(self._channels):
            if ci == active:
                ch_h = active_unit_h
                sub_h = active_unit_h
            else:
                ch_h = _INACTIVE_LANE_H
                sub_h = _INACTIVE_LANE_H
            lanes.append(_LaneInfo(ch_idx=ci, layer_idx=-1, top=y, height=ch_h))
            y += ch_h
            if ci in self._expanded_channels:
                n_layers = max(1, len(ch.layers))
                for li in range(n_layers):
                    lanes.append(_LaneInfo(ch_idx=ci, layer_idx=li, top=y, height=sub_h))
                    y += sub_h

        self._lanes_cache = lanes
        return lanes

    def _lane_at(self, x: float, y: float, lanes: list[_LaneInfo]) -> _LaneInfo | None:
        for lane in lanes:
            if lane.top <= y < lane.bottom:
                return lane
        return None

    def _active_lane(self, lanes: list[_LaneInfo]) -> _LaneInfo | None:
        """Return the composite lane for the active channel."""
        for lane in lanes:
            if lane.ch_idx == self._active_index and lane.is_channel:
                return lane
        return None

    def _lane_viewport(self, lane: _LaneInfo) -> Viewport:
        return replace(
            self._viewport,
            lane_top=lane.top,
            lane_height=max(1, lane.height),
        )

    def _toggle_expand(self, ch_idx: int) -> None:
        if ch_idx in self._expanded_channels:
            self._expanded_channels.discard(ch_idx)
        else:
            self._expanded_channels.add(ch_idx)
        self._invalidate_lanes()
        self.update()

    def _lane_at_y(self, y: float) -> int:
        """Backward-compat: return channel index for y (used internally)."""
        lanes = self._compute_lanes()
        lane = self._lane_at(0, y, lanes)
        return lane.ch_idx if lane else 0

    def _active_lane_vp(self) -> Viewport:
        lanes = self._compute_lanes()
        al = self._active_lane(lanes)
        if al:
            return self._lane_viewport(al)
        return self._viewport

    # ----------------------------------------------------------------- hit testing

    def _hit_test(self, t: float, lane_vp: Viewport) -> Action | None:
        if not self._editor or not self._editor.has_active_channel:
            return None
        # Hit test against active layer's actions, not synthesized
        ch = self._editor.active_channel
        li = self._editor.active_layer_index
        if not (0 <= li < len(ch.layers)):
            return None
        actions = ch.layers[li].actions
        if not actions or lane_vp.width == 0:
            return None
        tol = (_POINT_R + 3) / lane_vp.width * lane_vp.visible_time
        return actions.at_time(t, tol)

    def _hit_span_handle(
        self, x: float, layer, lane_vp: Viewport
    ) -> str | None:
        """Return 'span_start','span_end','fade_in','fade_out' or None."""
        if layer.span is None:
            return None
        start, end = layer.span
        x_start = lane_vp.time_to_x(start)
        x_end = lane_vp.time_to_x(end)

        # Fade handles take priority over span edges (they're inside the span)
        if layer.fade_in > 0:
            x_fi = lane_vp.time_to_x(start + layer.fade_in)
            if abs(x - x_fi) <= _HANDLE_TOL:
                return "fade_in"
        if layer.fade_out > 0:
            x_fo = lane_vp.time_to_x(end - layer.fade_out)
            if abs(x - x_fo) <= _HANDLE_TOL:
                return "fade_out"
        if abs(x - x_start) <= _HANDLE_TOL:
            return "span_start"
        if abs(x - x_end) <= _HANDLE_TOL:
            return "span_end"
        return None

    # ----------------------------------------------------------------- paint

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), _BG)
        self._draw_ruler(painter)
        self._draw_time_grid(painter)

        lanes = self._compute_lanes()
        sel = self._editor.selection if self._editor is not None else frozenset()
        active_li = self._editor.active_layer_index if self._editor is not None else 0

        for lane in lanes:
            ch = self._channels[lane.ch_idx] if lane.ch_idx < len(self._channels) else None
            if ch is None:
                continue
            color = _LANE_COLORS[lane.ch_idx % len(_LANE_COLORS)]
            is_active_ch = lane.ch_idx == self._active_index
            lane_vp = self._lane_viewport(lane)

            if lane.is_channel:
                self._draw_channel_lane(painter, lane, lane_vp, ch, is_active_ch, color, sel)
            else:
                is_active_layer = is_active_ch and (lane.layer_idx == active_li)
                self._draw_layer_lane(painter, lane, lane_vp, ch, lane.layer_idx,
                                      is_active_ch, is_active_layer, color, sel)

        # Active channel border
        for lane in lanes:
            if lane.is_channel and lane.ch_idx == self._active_index and len(self._channels) > 1:
                painter.setPen(QPen(_ACTIVE_BORDER, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(0, lane.top, self.width() - 1, lane.height - 1)

        if self._drag_mode == _DragMode.RUBBER_BAND:
            self._draw_rubber_band(painter)

        self._draw_chapter_markers(painter)
        self._draw_playhead(painter)
        painter.end()

    def _draw_channel_lane(
        self,
        painter: QPainter,
        lane: _LaneInfo,
        lane_vp: Viewport,
        channel: Channel,
        is_active: bool,
        color: QColor,
        selection: frozenset[float],
    ) -> None:
        actions = channel.synthesize()
        t0, t1 = lane_vp.time_window()

        # Guide lines
        painter.setPen(QPen(_GUIDE, 1))
        for guide_pos in (0, 25, 50, 75, 100):
            y = int(lane_vp.pos_to_y(float(guide_pos)))
            painter.drawLine(0, y, self.width(), y)

        # Waveform underlay — active channel only (avoids N redundant samples_for_range calls)
        if is_active:
            self._draw_waveform(painter, lane)

        # Expand/collapse toggle
        expand_char = "▼" if lane.ch_idx in self._expanded_channels else "▶"
        painter.setPen(_LABEL_FG)
        painter.drawText(4, lane.top + 14, expand_char)

        if len(actions) == 0:
            painter.drawText(_EXPAND_BTN_W + 4, lane.top + 14, channel.name)
            return

        lo, hi = actions.index_range(t0, t1)
        draw_lo = max(0, lo - 1)
        draw_hi = min(len(actions), hi + 1)
        if draw_hi <= draw_lo:
            painter.drawText(_EXPAND_BTN_W + 4, lane.top + 14, channel.name)
            return

        line_color = color if is_active else _dim_color(color, _DIM)
        xs, ys = self._get_coords(actions, draw_lo, draw_hi, lane_vp)

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

        # dot_start offsets xs/ys (which start at draw_lo) to the lo index
        dot_start = lo - draw_lo
        for k, i in enumerate(range(lo, hi)):
            a = actions[i]
            ax = int(xs[dot_start + k])
            ay = int(ys[dot_start + k])
            if a.at in selection:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_SEL_COLOR)
                painter.drawEllipse(ax - _SEL_R, ay - _SEL_R, _SEL_R * 2, _SEL_R * 2)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(line_color)
                painter.drawEllipse(ax - _POINT_R, ay - _POINT_R, _POINT_R * 2, _POINT_R * 2)

        painter.setPen(_LABEL_FG)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(_EXPAND_BTN_W + 4, lane.top + 14, channel.name)

    def _draw_layer_lane(
        self,
        painter: QPainter,
        lane: _LaneInfo,
        lane_vp: Viewport,
        channel: Channel,
        layer_idx: int,
        is_active_ch: bool,
        is_active_layer: bool,
        color: QColor,
        selection: frozenset[float],
    ) -> None:
        if not (0 <= layer_idx < len(channel.layers)):
            return
        layer = channel.layers[layer_idx]

        # Subtle sub-lane background
        painter.fillRect(0, lane.top, self.width(), lane.height, _SUBLANE_BG)

        # Span block
        if layer.span is not None:
            start, end = layer.span
            x_start = int(lane_vp.time_to_x(start))
            x_end = int(lane_vp.time_to_x(end))
            span_w = max(1, x_end - x_start)
            span_rect = QRectF(x_start, lane.top, span_w, lane.height)
            painter.fillRect(span_rect, _SPAN_FILL)
            painter.setPen(QPen(_SPAN_BORDER, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(span_rect)

            # Fade-in region (left ramp)
            if layer.fade_in > 0:
                x_fi = int(lane_vp.time_to_x(start + layer.fade_in))
                painter.setPen(QPen(_FADE_HANDLE, 2))
                painter.drawLine(x_fi, lane.top + 2, x_fi, lane.bottom - 2)
                # Small handle triangle
                self._draw_handle_triangle(painter, x_fi, lane.top + lane.height // 2,
                                           _FADE_HANDLE, facing_right=True)

            # Fade-out region (right ramp)
            if layer.fade_out > 0:
                x_fo = int(lane_vp.time_to_x(end - layer.fade_out))
                painter.setPen(QPen(_FADE_HANDLE, 2))
                painter.drawLine(x_fo, lane.top + 2, x_fo, lane.bottom - 2)
                self._draw_handle_triangle(painter, x_fo, lane.top + lane.height // 2,
                                           _FADE_HANDLE, facing_right=False)

        # Layer action nodes
        if len(layer.actions) == 0:
            pass
        else:
            t0, t1 = lane_vp.time_window()
            lo, hi = layer.actions.index_range(t0, t1)
            draw_lo = max(0, lo - 1)
            draw_hi = min(len(layer.actions), hi + 1)

            if is_active_layer:
                node_color = color
            elif is_active_ch:
                node_color = _dim_color(color, _GHOST_ALPHA * 3)
            else:
                node_color = _dim_color(color, _GHOST_ALPHA)

            if draw_hi > draw_lo:
                xs, ys = self._get_coords(layer.actions, draw_lo, draw_hi, lane_vp)
                painter.setPen(QPen(node_color, 1 if not is_active_layer else 2))
                for j in range(len(xs) - 1):
                    painter.drawLine(int(xs[j]), int(ys[j]), int(xs[j + 1]), int(ys[j + 1]))

                dot_start = lo - draw_lo
                for k, i in enumerate(range(lo, hi)):
                    a = layer.actions[i]
                    ax = int(xs[dot_start + k])
                    ay = int(ys[dot_start + k])
                    if is_active_layer and a.at in selection:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(_SEL_COLOR)
                        painter.drawEllipse(ax - _SEL_R, ay - _SEL_R, _SEL_R * 2, _SEL_R * 2)
                    else:
                        r = _POINT_R if is_active_layer else max(1, _POINT_R - 1)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(node_color)
                        painter.drawEllipse(ax - r, ay - r, r * 2, r * 2)

        # Layer label
        from wombat.domain.channel import BlendMode
        blend_badge = "ADD" if layer.blend == BlendMode.ADDITIVE else "OVR"
        enabled_mark = "" if layer.enabled else "[off] "
        label = f"  {enabled_mark}{blend_badge} {layer.name}"
        label_color = color if is_active_layer else _dim_color(_LABEL_FG, 0.7)
        painter.setPen(label_color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(4, lane.top + 13, label)

    def _draw_handle_triangle(
        self,
        painter: QPainter,
        cx: int,
        cy: int,
        color: QColor,
        facing_right: bool,
    ) -> None:
        size = 5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint
        if facing_right:
            pts = [QPoint(cx, cy - size), QPoint(cx + size, cy), QPoint(cx, cy + size)]
        else:
            pts = [QPoint(cx, cy - size), QPoint(cx - size, cy), QPoint(cx, cy + size)]
        painter.drawPolygon(pts)

    def _draw_time_grid(self, painter: QPainter) -> None:
        top = _RULER_H
        bottom = self.height()
        t0, t1 = self._viewport.time_window()

        interval = _nice_tick_interval(self._viewport.visible_time)
        first_tick = math.ceil(t0 / interval) * interval
        grid_pen = QPen(_GRID_LINE, 1)
        grid_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)
        t = first_tick
        while t <= t1 + interval * 0.01:
            if abs(t) > 1e-9:
                x = int(self._viewport.time_to_x(t))
                if 0 <= x <= self.width():
                    painter.drawLine(x, top, x, bottom)
            t += interval

        x0 = int(self._viewport.time_to_x(0.0))
        if 0 <= x0 <= self.width():
            painter.setPen(QPen(_T0_LINE, 1))
            painter.drawLine(x0, top, x0, bottom)

    def _draw_ruler(self, painter: QPainter) -> None:
        painter.fillRect(QRect(0, 0, self.width(), _RULER_H), _RULER_BG)
        painter.setPen(QPen(_RULER_FG, 1))
        painter.drawLine(0, _RULER_H - 1, self.width(), _RULER_H - 1)

        interval = _nice_tick_interval(self._viewport.visible_time)
        t0, t1 = self._viewport.time_window()
        first_tick = math.ceil(t0 / interval) * interval

        font = painter.font()
        font.setPointSizeF(font.pointSizeF() * 1.15)
        painter.setFont(font)
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
                    painter.drawText(x + 3, _RULER_H - 7, label)
            t += interval

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

    def _render_waveform_pixmap(self, lane_height: int) -> None:
        """Pre-render a 3× wide waveform pixmap into _waveform_pixmap_cache.

        Covers [t0 - vis_time, t0 + 2*vis_time] so ~vis_time of playback elapses
        before the next miss.  Uses numpy broadcasting to fill pixels — no QPointF.
        """
        from PySide6.QtGui import QImage, QPixmap

        w = self.width()
        h = lane_height
        if w <= 0 or h <= 0 or self._waveform is None:
            self._waveform_pixmap_cache[h] = (QPixmap(), 0.0, 0.0,
                                               self._viewport.visible_time, w)
            return

        vis_time = self._viewport.visible_time
        t0, _ = self._viewport.time_window()
        pre_t0 = t0 - vis_time
        pre_t1 = t0 + 2.0 * vis_time
        pre_w = w * 3

        amplitudes = self._waveform.samples_for_range(pre_t0, pre_t1, pre_w)

        half_h = h / 2.0 * 0.9
        cy = h / 2.0
        rows = np.arange(h, dtype=np.float32)[:, np.newaxis]          # (h, 1)
        amps_px = (amplitudes.astype(np.float32) * half_h)[np.newaxis, :]  # (1, pre_w)
        mask = np.abs(rows - cy) < amps_px                             # (h, pre_w)

        img_arr = np.zeros((h, pre_w, 4), dtype=np.uint8)
        # _WAVEFORM_FILL_ACTIVE = QColor(80, 180, 255, 55)
        img_arr[mask] = [80, 180, 255, 55]
        img_arr = np.ascontiguousarray(img_arr)

        qimg = QImage(img_arr.data, pre_w, h, pre_w * 4,
                      QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        self._waveform_pixmap_cache[h] = (pixmap, pre_t0, pre_t1, vis_time, w)

    def _draw_waveform(self, painter: QPainter, lane: _LaneInfo) -> None:
        """Draw the audio waveform underlay for the active channel only."""
        if not self._show_waveform or self._waveform is None:
            return
        w = self.width()
        h = lane.height
        if w <= 0 or h <= 0:
            return

        t0, t1 = self._viewport.time_window()
        vis_time = self._viewport.visible_time

        entry = self._waveform_pixmap_cache.get(h)
        if entry is not None:
            _, pre_t0, pre_t1, cached_vis, cached_w = entry
            valid = (cached_vis == vis_time and cached_w == w
                     and t0 >= pre_t0 and t1 <= pre_t1)
        else:
            valid = False

        if not valid:
            self._render_waveform_pixmap(h)
            entry = self._waveform_pixmap_cache.get(h)

        if entry is None:
            return
        pixmap, pre_t0, pre_t1, _, _ = entry
        if pixmap.isNull():
            return

        pre_dur = pre_t1 - pre_t0
        pre_w = pixmap.width()
        src_x = (t0 - pre_t0) / pre_dur * pre_w
        src_w = (t1 - t0) / pre_dur * pre_w
        src_rect = QRectF(src_x, 0.0, src_w, float(h))
        dst_rect = QRectF(0.0, float(lane.top), float(w), float(h))
        painter.drawPixmap(dst_rect, pixmap, src_rect)

    def _draw_chapter_markers(self, painter: QPainter) -> None:
        if self._project is None or not self._project.chapters:
            return
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPolygon
        t0, t1 = self._viewport.time_window()
        painter.save()
        fm = painter.fontMetrics()
        for ch in self._project.chapters:
            if ch.at < t0 - 1.0 or ch.at > t1 + 1.0:
                continue
            x = int(self._viewport.time_to_x(ch.at))
            if not (-4 <= x <= self.width() + 4):
                continue
            # Downward triangle in the ruler strip
            tri = QPolygon([QPoint(x - 5, 1), QPoint(x + 5, 1), QPoint(x, _RULER_H - 3)])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_CHAPTER_COLOR)
            painter.drawPolygon(tri)
            # Thin vertical line through the lane area
            painter.setPen(QPen(_CHAPTER_COLOR, 1, Qt.PenStyle.DashLine))
            painter.drawLine(x, _RULER_H, x, self.height())
            # Label
            if ch.name:
                painter.setPen(QPen(_CHAPTER_COLOR, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                label_x = x + 4
                if label_x + fm.horizontalAdvance(ch.name) > self.width():
                    label_x = x - 4 - fm.horizontalAdvance(ch.name)
                painter.drawText(label_x, _RULER_H - 4, ch.name)
        painter.restore()

    def _draw_playhead(self, painter: QPainter) -> None:
        x = int(self._viewport.time_to_x(self._playhead_time))
        if 0 <= x <= self.width():
            painter.setPen(QPen(_PLAYHEAD_COLOR, 1))
            painter.drawLine(x, 0, x, self.height())
