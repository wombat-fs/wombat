"""ZoomControl — a compact horizontal-scale control strip for the timeline.

Sits below the timeline canvas. 1× is the default span; higher values show a
shorter span (zoomed in, for fine edits), lower values show more. Mirrors the
Ctrl+wheel zoom already on the canvas and stays in sync with it via the
TimelineWidget.zoom_changed signal.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from wombat.ui.timeline.timeline_widget import TimelineWidget

_PRESETS: list[float] = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
_STEP = 1.5  # multiplicative step for the −/+ buttons


def _fmt(level: float) -> str:
    return f"{level:g}×"


class ZoomControl(QWidget):
    def __init__(self, timeline: TimelineWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._timeline = timeline

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 1, 4, 1)
        row.setSpacing(3)
        row.addStretch()
        row.addWidget(QLabel("Zoom"))

        self._btn_out = QPushButton("−")
        self._btn_out.setFixedWidth(24)
        self._btn_out.setToolTip("Zoom out — show more of the timeline")

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._combo.setFixedWidth(74)
        self._combo.setToolTip(
            "Timeline horizontal scale (1× = default). Ctrl+scroll on the "
            "timeline also zooms."
        )
        for p in _PRESETS:
            self._combo.addItem(_fmt(p), p)
        self._combo.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn_in = QPushButton("+")
        self._btn_in.setFixedWidth(24)
        self._btn_in.setToolTip("Zoom in — show less for fine edits")

        self._btn_reset = QPushButton("1×")
        self._btn_reset.setFixedWidth(28)
        self._btn_reset.setToolTip("Reset to 1×")

        row.addWidget(self._btn_out)
        row.addWidget(self._combo)
        row.addWidget(self._btn_in)
        row.addWidget(self._btn_reset)

        self._btn_out.clicked.connect(lambda: self._timeline.zoom_by(1.0 / _STEP))
        self._btn_in.clicked.connect(lambda: self._timeline.zoom_by(_STEP))
        self._btn_reset.clicked.connect(lambda: self._timeline.set_zoom_level(1.0))
        self._combo.activated.connect(self._on_preset_chosen)
        self._combo.lineEdit().editingFinished.connect(self._on_text_entered)

        timeline.zoom_changed.connect(self._on_zoom_changed)
        self._on_zoom_changed(timeline.zoom_level())

    # ----------------------------------------------------------------- slots

    def _on_preset_chosen(self, index: int) -> None:
        level = self._combo.itemData(index)
        if level is not None:
            self._timeline.set_zoom_level(float(level))

    def _on_text_entered(self) -> None:
        text = self._combo.lineEdit().text().strip().rstrip("×xX").strip()
        try:
            level = float(text)
        except ValueError:
            self._on_zoom_changed(self._timeline.zoom_level())  # revert display
            return
        self._timeline.set_zoom_level(level)

    def _on_zoom_changed(self, level: float) -> None:
        self._combo.blockSignals(True)
        self._combo.setCurrentText(_fmt(level))
        self._combo.blockSignals(False)
