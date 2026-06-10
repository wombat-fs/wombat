"""Speed-to-color gradient for heatmap lane rendering.

Maps stroke speed (pos-units/second) through a blue→cyan→green→yellow→red
gradient matching the HSV range 240°→0°.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

MAX_SPEED: float = 400.0


def speed_color(speed: float) -> QColor:
    """Map speed to a heatmap color; clamps at MAX_SPEED."""
    t = max(0.0, min(1.0, speed / MAX_SPEED))
    hue = (1.0 - t) * (240.0 / 360.0)
    return QColor.fromHsvF(hue, 1.0, 1.0)
