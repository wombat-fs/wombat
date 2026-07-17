"""RecordingPanel — dock widget for the Recording scripting mode.

Shows a large vertical slider (position 0–100) and a Record button.
The slider drives RecordingMode.set_value(); the button drives toggle_recording().
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from wombat.ui.scripting.mode import RecordingMode


class RecordingPanel(QWidget):
    def __init__(self, mode: RecordingMode, parent=None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._record_btn = QPushButton("● Record")
        self._record_btn.setCheckable(True)
        self._record_btn.setToolTip("Start / stop recording (samples slider position at ~30 Hz)")
        self._record_btn.toggled.connect(self._on_record_toggled)
        layout.addWidget(self._record_btn)

        self._slider = QSlider(Qt.Orientation.Vertical)
        self._slider.setRange(0, 100)
        self._slider.setValue(50)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
        self._slider.setTickInterval(10)
        self._slider.setToolTip(
            "Current position (0–100).  Drag during recording to capture motion."
        )
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider, stretch=1, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._value_label = QLabel("50")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value_label)

    # ----------------------------------------------------------------- slots

    @Slot(bool)
    def _on_record_toggled(self, checked: bool) -> None:
        self._mode.toggle_recording()
        self._update_record_button()

    @Slot(int)
    def _on_slider_changed(self, v: int) -> None:
        self._mode.set_value(v)
        self._value_label.setText(str(v))

    # ----------------------------------------------------------------- sync

    def sync_recording_state(self) -> None:
        """Sync button visual state from the mode (e.g. after auto-stop)."""
        self._update_record_button()

    def _update_record_button(self) -> None:
        recording = self._mode.is_recording
        self._record_btn.blockSignals(True)
        self._record_btn.setChecked(recording)
        self._record_btn.blockSignals(False)
        if recording:
            self._record_btn.setText("■ Stop")
            self._record_btn.setStyleSheet("QPushButton { color: #e04040; font-weight: bold; }")
        else:
            self._record_btn.setText("● Record")
            self._record_btn.setStyleSheet("")
