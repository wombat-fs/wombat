"""Transport bar — play/pause, seek, frame-step, time/fps readout, speed control."""
import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from wombat.playback.player import VideoPlayer

log = logging.getLogger(__name__)

_SPEEDS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0]
_DEFAULT_SPEED_IDX = 4  # 1.0×


def _fmt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    m = int(seconds) // 60
    s = seconds - m * 60
    return f"{m:02d}:{s:06.3f}"


class TransportBar(QWidget):
    """Transport controls driven by and driving a VideoPlayer instance."""

    def __init__(self, player: VideoPlayer, parent=None) -> None:
        super().__init__(parent)
        self._player = player
        self._dragging = False  # True while user holds the seek slider

        self._build_ui()
        self._connect_player()
        self._update_enabled(False)

    # ----------------------------------------------------------------- build UI

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(4, 2, 4, 2)
        vbox.setSpacing(2)

        # --- seek row ---
        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 10000)
        self._seek_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        vbox.addWidget(self._seek_slider)

        # --- controls row ---
        hbox = QHBoxLayout()
        hbox.setSpacing(4)

        self._btn_step_back = QPushButton("◀|")
        self._btn_step_back.setFixedWidth(36)
        self._btn_step_back.setToolTip("Step back one frame")

        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedWidth(36)
        self._btn_play.setToolTip("Play / Pause")

        self._btn_step_fwd = QPushButton("|▶")
        self._btn_step_fwd.setFixedWidth(36)
        self._btn_step_fwd.setToolTip("Step forward one frame")

        self._time_label = QLabel("00:00.000 / 00:00.000")
        self._time_label.setToolTip("Current / Duration")

        self._fps_label = QLabel("-- fps")
        self._fps_label.setMinimumWidth(60)

        self._speed_combo = QComboBox()
        for s in _SPEEDS:
            self._speed_combo.addItem(f"{s}×")
        self._speed_combo.setCurrentIndex(_DEFAULT_SPEED_IDX)
        self._speed_combo.setToolTip("Playback speed")
        self._speed_combo.setFixedWidth(70)

        hbox.addWidget(self._btn_step_back)
        hbox.addWidget(self._btn_play)
        hbox.addWidget(self._btn_step_fwd)
        hbox.addSpacing(8)
        hbox.addWidget(self._time_label)
        hbox.addStretch()
        hbox.addWidget(self._fps_label)
        hbox.addSpacing(8)
        hbox.addWidget(self._speed_combo)

        vbox.addLayout(hbox)

    # ----------------------------------------------------------------- wiring

    def _connect_player(self) -> None:
        p = self._player

        # player → UI
        p.video_loaded.connect(self._on_video_loaded)
        p.position_changed.connect(self._on_position_changed)
        p.duration_changed.connect(self._on_duration_changed)
        p.playback_changed.connect(self._on_playback_changed)

        # UI → player
        self._btn_play.clicked.connect(self._player.toggle_play)
        self._btn_step_back.clicked.connect(lambda: self._player.step_frame(forward=False))
        self._btn_step_fwd.clicked.connect(lambda: self._player.step_frame(forward=True))

        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)

        self._speed_combo.currentIndexChanged.connect(self._on_speed_changed)

    # ----------------------------------------------------------------- slots

    @Slot(str)
    def _on_video_loaded(self, path: str) -> None:
        self._update_enabled(True)
        fps = self._player.fps
        self._fps_label.setText(f"{fps:.3f} fps" if fps > 0 else "-- fps")

    @Slot(float)
    def _on_position_changed(self, seconds: float) -> None:
        if not self._dragging:
            dur = self._player.duration
            if dur > 0:
                pos = int(seconds / dur * 10000)
                self._seek_slider.setValue(pos)
        self._time_label.setText(
            f"{_fmt_time(seconds)} / {_fmt_time(self._player.duration)}"
        )

    @Slot(float)
    def _on_duration_changed(self, duration: float) -> None:
        self._time_label.setText(
            f"{_fmt_time(self._player.actual_time)} / {_fmt_time(duration)}"
        )
        fps = self._player.fps
        if fps > 0:
            self._fps_label.setText(f"{fps:.3f} fps")

    @Slot(bool)
    def _on_playback_changed(self, is_paused: bool) -> None:
        self._btn_play.setText("▶" if is_paused else "⏸")

    @Slot()
    def _on_slider_pressed(self) -> None:
        self._dragging = True

    @Slot()
    def _on_slider_released(self) -> None:
        self._dragging = False
        dur = self._player.duration
        if dur > 0:
            t = self._seek_slider.value() / 10000.0 * dur
            self._player.seek_exact(t)

    @Slot(int)
    def _on_slider_moved(self, value: int) -> None:
        dur = self._player.duration
        if dur > 0:
            t = value / 10000.0 * dur
            self._player.seek_exact(t)

    @Slot(int)
    def _on_speed_changed(self, index: int) -> None:
        if 0 <= index < len(_SPEEDS):
            self._player.set_speed(_SPEEDS[index])

    # ----------------------------------------------------------------- helpers

    def _update_enabled(self, loaded: bool) -> None:
        for w in (
            self._btn_play,
            self._btn_step_back,
            self._btn_step_fwd,
            self._seek_slider,
            self._speed_combo,
        ):
            w.setEnabled(loaded)
