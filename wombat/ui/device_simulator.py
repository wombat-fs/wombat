"""DeviceSimulator — transparent overlay showing synthesized device position.

Renders a draggable two-endpoint bar over the video widget, mirroring
OFS's ScriptSimulator. P1 (top/100%) and P2 (bottom/0%) can be dragged
independently to move, rotate, and resize the bar. The centre handle
moves both endpoints together.

Coordinates are stored as fractions [0,1] of the widget dimensions so
the bar stays in the same relative position across resizes.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from wombat.domain.interpolate import value_at

if TYPE_CHECKING:
    from wombat.app.project import Project
    from wombat.playback.player import VideoPlayer

# OFS-inspired colour palette
_BACK_COLOR   = QColor(16,  16,  16,  192)   # bar background
_BORDER_COLOR = QColor(11,  79,  108, 230)   # bar border / tick marks
_FRONT_COLOR  = QColor(1,   186, 239, 230)   # filled portion (#01BAEF)
_HANDLE_COLOR = QColor(255, 255, 255, 180)   # endpoint circles
_TEXT_COLOR   = QColor(255, 255, 255, 220)

_BAR_WIDTH       = 26.0   # total bar width in px (incl. border)
_BORDER_WIDTH    =  4.0   # border ring width
_INNER_WIDTH     = _BAR_WIDTH - _BORDER_WIDTH * 2

_HANDLE_RADIUS   =  8     # px — endpoint hit radius
_CENTER_RADIUS   = 14     # px — centre-drag hit radius

# Default bar: vertical, right-hand side of the video
_DEFAULT_P1 = (0.87, 0.12)   # top   endpoint (pos = 100)
_DEFAULT_P2 = (0.87, 0.88)   # bottom endpoint (pos = 0)


def _dist(a: QPointF, b: QPointF) -> float:
    dx, dy = a.x() - b.x(), a.y() - b.y()
    return math.sqrt(dx * dx + dy * dy)


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


class SimulatorOverlay(QWidget):
    """Transparent overlay that draws and animates the device-position bar.

    Parent widget should be the video widget (MpvWidget). The overlay
    always fills the parent; an event filter installed by the caller
    keeps its geometry in sync on resize.

    Drag interactions
    -----------------
    - Near P1 or P2 endpoint circles → drag that endpoint (rotates / scales bar)
    - Near the bar centre            → drag both endpoints (moves bar)
    - Anywhere else                  → event propagates to video widget
    """

    def __init__(
        self, player: VideoPlayer, project: Project, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)

        self._player = player
        self._project = project
        self._position: float = 0.0
        self._has_data: bool = False

        # Fractional [0,1] coords; P1 = top (100%), P2 = bottom (0%)
        self._p1f = QPointF(*_DEFAULT_P1)
        self._p2f = QPointF(*_DEFAULT_P2)

        # Drag state
        self._drag_mode: str | None = None   # 'p1' | 'p2' | 'center'
        self._drag_origin_mouse = QPointF()
        self._drag_origin_p1    = QPointF()
        self._drag_origin_p2    = QPointF()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

        player.position_changed.connect(self._on_position)

    # ------------------------------------------------------------------ API

    def set_project(self, project: Project) -> None:
        self._project = project
        self._position = 0.0
        self._has_data = False
        self.update()

    def reset_position(self) -> None:
        self._p1f = QPointF(*_DEFAULT_P1)
        self._p2f = QPointF(*_DEFAULT_P2)
        self.update()

    # ------------------------------------------------------------------ coords

    def _p1_px(self) -> QPointF:
        return QPointF(self._p1f.x() * self.width(), self._p1f.y() * self.height())

    def _p2_px(self) -> QPointF:
        return QPointF(self._p2f.x() * self.width(), self._p2f.y() * self.height())

    def _center_px(self) -> QPointF:
        p1, p2 = self._p1_px(), self._p2_px()
        return QPointF((p1.x() + p2.x()) * 0.5, (p1.y() + p2.y()) * 0.5)

    # ------------------------------------------------------------------ slot

    @Slot(float)
    def _on_position(self, t: float) -> None:
        channels = self._project.channels
        if not channels:
            self._has_data = False
            self.update()
            return
        idx = max(0, min(self._project.active_index, len(channels) - 1))
        ch = channels[idx]
        if not ch.enabled or not ch.layers:
            self._has_data = False
            self.update()
            return
        actions = ch.synthesize()
        self._has_data = len(actions) > 0
        self._position = value_at(actions, t) if self._has_data else 0.0
        self.update()

    # ------------------------------------------------------------------ paint

    def paintEvent(self, _ev) -> None:  # type: ignore[override]
        p1 = self._p1_px()
        p2 = self._p2_px()
        length = _dist(p1, p2)
        if length < 2.0:
            return

        # Unit vector from p2 → p1  (the "positive" direction)
        dir_x = (p1.x() - p2.x()) / length
        dir_y = (p1.y() - p2.y()) / length
        # Perpendicular (left of direction)
        perp_x, perp_y = -dir_y, dir_x

        percent = self._position / 100.0
        fill_end = QPointF(
            p2.x() + dir_x * length * percent,
            p2.y() + dir_y * length * percent,
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ---- Border ----
        pen = QPen(_BORDER_COLOR, _BAR_WIDTH + _BORDER_WIDTH,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(p1, p2)

        # ---- Background ----
        pen = QPen(_BACK_COLOR, _BAR_WIDTH, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(p1, p2)

        # ---- Fill (pos=0 at p2, pos=100 at p1) ----
        if self._has_data:
            pen = QPen(_FRONT_COLOR, _INNER_WIDTH, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(p2, fill_end)

        # ---- Tick marks at 10% intervals ----
        half = _INNER_WIDTH * 0.5
        tick_pen = QPen(_BORDER_COLOR, 1.5)
        painter.setPen(tick_pen)
        for i in range(1, 10):
            frac = i / 10.0
            cx = p2.x() + dir_x * length * frac
            cy = p2.y() + dir_y * length * frac
            painter.drawLine(
                QPointF(cx + perp_x * half, cy + perp_y * half),
                QPointF(cx - perp_x * half, cy - perp_y * half),
            )

        # ---- Position number ----
        if self._has_data:
            centre = self._center_px()
            # Offset slightly to the side so it doesn't sit on the bar
            offset_x = perp_x * (_BAR_WIDTH * 0.5 + 6)
            offset_y = perp_y * (_BAR_WIDTH * 0.5 + 6)
            painter.setPen(QPen(_TEXT_COLOR))
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QPointF(centre.x() + offset_x, centre.y() + offset_y + 5),
                f"{int(self._position)}",
            )

        # ---- Endpoint handles ----
        painter.setBrush(_HANDLE_COLOR)
        painter.setPen(QPen(Qt.GlobalColor.white, 1.0))
        r = _HANDLE_RADIUS - 2
        painter.drawEllipse(p1, r, r)
        painter.drawEllipse(p2, r, r)

        painter.end()

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        pos = ev.position()
        if _dist(pos, self._p1_px()) <= _HANDLE_RADIUS + 4:
            self._drag_mode = "p1"
            self._drag_origin_mouse = pos
            self._drag_origin_p1 = QPointF(self._p1f)
            ev.accept()
        elif _dist(pos, self._p2_px()) <= _HANDLE_RADIUS + 4:
            self._drag_mode = "p2"
            self._drag_origin_mouse = pos
            self._drag_origin_p2 = QPointF(self._p2f)
            ev.accept()
        elif _dist(pos, self._center_px()) <= _CENTER_RADIUS:
            self._drag_mode = "center"
            self._drag_origin_mouse = pos
            self._drag_origin_p1 = QPointF(self._p1f)
            self._drag_origin_p2 = QPointF(self._p2f)
            ev.accept()
        else:
            ev.ignore()

    def mouseMoveEvent(self, ev) -> None:  # type: ignore[override]
        pos = ev.position()
        if self._drag_mode is None:
            # Hover cursor hint
            if (
                _dist(pos, self._p1_px()) <= _HANDLE_RADIUS + 4
                or _dist(pos, self._p2_px()) <= _HANDLE_RADIUS + 4
                or _dist(pos, self._center_px()) <= _CENTER_RADIUS
            ):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.unsetCursor()
            ev.ignore()
            return

        w, h = self.width() or 1, self.height() or 1
        dx = (pos.x() - self._drag_origin_mouse.x()) / w
        dy = (pos.y() - self._drag_origin_mouse.y()) / h

        if self._drag_mode == "p1":
            self._p1f = QPointF(
                _clamp01(self._drag_origin_p1.x() + dx),
                _clamp01(self._drag_origin_p1.y() + dy),
            )
        elif self._drag_mode == "p2":
            self._p2f = QPointF(
                _clamp01(self._drag_origin_p2.x() + dx),
                _clamp01(self._drag_origin_p2.y() + dy),
            )
        elif self._drag_mode == "center":
            self._p1f = QPointF(
                _clamp01(self._drag_origin_p1.x() + dx),
                _clamp01(self._drag_origin_p1.y() + dy),
            )
            self._p2f = QPointF(
                _clamp01(self._drag_origin_p2.x() + dx),
                _clamp01(self._drag_origin_p2.y() + dy),
            )

        self.update()
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:  # type: ignore[override]
        if self._drag_mode is not None:
            self._drag_mode = None
            ev.accept()
        else:
            ev.ignore()

    def contextMenuEvent(self, ev) -> None:  # type: ignore[override]
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Reset position", self.reset_position)
        menu.exec(ev.globalPos())
        ev.accept()
