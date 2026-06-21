"""Render a funscript speed heatmap to a standalone image (OFS-style strip).

Each segment between consecutive actions is filled with a color derived from its
stroke speed (|Δpos|/Δt, capped at MAX_SPEED) using the same gradient as the
timeline lane. Optionally draws a chapter strip with labels beneath the heatmap.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from wombat.domain.action import ActionList
from wombat.domain.chapter import Chapter
from wombat.ui.timeline.heatmap import speed_color

_BG = QColor(20, 20, 20)
_CHAPTER_STRIP_H = 22
_CHAPTER_BG = QColor(34, 34, 34)
_RANGE_FILL = QColor(70, 110, 160, 180)
_RANGE_EDGE = QColor(235, 235, 235)
_POINT_TICK = QColor(255, 210, 90)
_LABEL_FG = QColor(238, 238, 238)


def render_heatmap(
    actions: ActionList,
    duration: float,
    width: int = 2000,
    height: int = 60,
    chapters: list[Chapter] | None = None,
) -> QImage:
    """Return an RGB image of the heatmap. When chapters is given, append a labeled strip."""
    strip_h = _CHAPTER_STRIP_H if chapters else 0
    img = QImage(width, height + strip_h, QImage.Format.Format_RGB32)
    img.fill(_BG)
    if duration <= 0 or len(actions) < 2:
        return img

    p = QPainter(img)
    try:
        for j in range(len(actions) - 1):
            a1 = actions[j]
            a2 = actions[j + 1]
            dt = a2.at - a1.at
            if dt <= 0:
                continue
            spd = abs(a2.pos - a1.pos) / dt
            x0 = a1.at / duration * width
            x1 = a2.at / duration * width
            p.fillRect(QRectF(x0, 0.0, x1 - x0, float(height)), speed_color(spd))
        if chapters:
            _draw_chapters(p, chapters, duration, width, height, strip_h)
    finally:
        p.end()
    return img


def _draw_chapters(
    p: QPainter,
    chapters: list[Chapter],
    duration: float,
    width: int,
    height: int,
    strip_h: int,
) -> None:
    top = float(height)
    p.fillRect(QRectF(0.0, top, float(width), float(strip_h)), _CHAPTER_BG)
    font = p.font()
    font.setPixelSize(12)
    p.setFont(font)
    align = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

    for ch in chapters:
        x0 = ch.at / duration * width
        if ch.is_range and ch.end is not None:
            x1 = ch.end / duration * width
            p.fillRect(QRectF(x0, top, x1 - x0, float(strip_h)), _RANGE_FILL)
            p.setPen(_RANGE_EDGE)
            p.drawLine(int(x0), int(top), int(x0), int(top + strip_h))
            p.drawLine(int(x1), int(top), int(x1), int(top + strip_h))
            label_x = x0 + 3
            label_w = max(0.0, x1 - x0 - 4)
        else:
            p.setPen(_POINT_TICK)
            p.drawLine(int(x0), int(top), int(x0), int(top + strip_h))
            label_x = x0 + 3
            label_w = width - label_x
        if ch.name:
            p.setPen(_LABEL_FG)
            p.drawText(QRectF(label_x, top, label_w, float(strip_h)), align, ch.name)
