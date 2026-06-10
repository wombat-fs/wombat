"""Viewport — pure time/pos ↔ pixel coordinate mapping.

No Qt imports. Fully unit-testable without a display.
Time runs left→right; pos runs bottom(0)→top(100), matching funscript convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class Viewport:
    offset: float        # seconds at the left edge of the canvas
    visible_time: float  # seconds spanned across the canvas width
    width: int           # canvas pixel width
    lane_top: int        # lane rect top (px)
    lane_height: int     # lane rect height (px)

    MIN_VISIBLE: ClassVar[float] = 1.0
    MAX_VISIBLE: ClassVar[float] = 300.0

    def time_to_x(self, t: float) -> float:
        if self.width == 0 or self.visible_time == 0:
            return 0.0
        return (t - self.offset) / self.visible_time * self.width

    def x_to_time(self, x: float) -> float:
        if self.width == 0 or self.visible_time == 0:
            return self.offset
        return self.offset + x / self.width * self.visible_time

    def pos_to_y(self, pos: float) -> float:
        return self.lane_top + (1.0 - pos / 100.0) * self.lane_height

    def y_to_pos(self, y: float) -> float:
        if self.lane_height == 0:
            return 0.0
        return (1.0 - (y - self.lane_top) / self.lane_height) * 100.0

    def zoom(self, factor: float, anchor_x: float) -> Viewport:
        """Zoom by factor, keeping the time under anchor_x fixed."""
        anchor_t = self.x_to_time(anchor_x)
        new_vt = max(self.MIN_VISIBLE, min(self.MAX_VISIBLE, self.visible_time * factor))
        frac = anchor_x / self.width if self.width else 0.0
        new_offset = anchor_t - frac * new_vt
        return Viewport(
            offset=new_offset,
            visible_time=new_vt,
            width=self.width,
            lane_top=self.lane_top,
            lane_height=self.lane_height,
        )

    def pan(self, dx_seconds: float) -> Viewport:
        return Viewport(
            offset=self.offset + dx_seconds,
            visible_time=self.visible_time,
            width=self.width,
            lane_top=self.lane_top,
            lane_height=self.lane_height,
        )

    def time_window(self) -> tuple[float, float]:
        return (self.offset, self.offset + self.visible_time)
