"""VideoPlayer — control/state API wrapping python-mpv.

Threading model: mpv property observer and event callbacks run on mpv's internal
event thread. Emitting Qt signals from there is safe: PySide6 uses AutoConnection,
which delivers the signal via the event loop of the receiving object's thread (the
GUI thread) when sender and receiver are in different threads.
"""
import logging

import mpv
from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


class VideoPlayer(QObject):
    """Owns the mpv.MPV instance; MpvWidget is handed the handle for rendering.

    Two notions of current position:
    - logical_time: the time we last *requested* (set immediately on seek/step).
      The timeline cursor reads this so it never jitters or rubber-bands.
    - actual_time: what mpv reports. Lags a frame or two behind seeks.
    While playing, logical_time tracks actual_time continuously.
    """

    video_loaded = Signal(str)      # path
    duration_changed = Signal(float)    # seconds
    position_changed = Signal(float)    # seconds (actual, player-reported)
    playback_changed = Signal(bool)     # True = paused
    speed_changed = Signal(float)
    end_reached = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._mpv = mpv.MPV(vo="libmpv", hr_seek="yes", keep_open="yes", pause=True)
        self._logical_time: float = 0.0
        self._actual_time: float = 0.0
        self._duration: float = 0.0
        self._fps: float = 0.0
        self._is_paused: bool = True
        self._is_loaded: bool = False
        self._speed: float = 1.0
        self._setup_observers()

    @property
    def mpv(self) -> mpv.MPV:
        return self._mpv

    # ----------------------------------------------------------------- observers

    def _setup_observers(self) -> None:
        @self._mpv.property_observer("time-pos")
        def _on_time_pos(name, value):
            if value is not None:
                self._actual_time = float(value)
                if not self._is_paused:
                    # While playing, logical follows actual
                    self._logical_time = self._actual_time
                else:
                    # While paused (includes after step_frame), keep in sync
                    self._logical_time = self._actual_time
                self.position_changed.emit(self._actual_time)

        @self._mpv.property_observer("duration")
        def _on_duration(name, value):
            if value is not None:
                self._duration = float(value)
                self.duration_changed.emit(self._duration)

        @self._mpv.property_observer("pause")
        def _on_pause(name, value):
            if value is not None:
                self._is_paused = bool(value)
                self.playback_changed.emit(self._is_paused)

        @self._mpv.property_observer("speed")
        def _on_speed(name, value):
            if value is not None:
                self._speed = float(value)
                self.speed_changed.emit(self._speed)

        @self._mpv.event_callback("file-loaded")
        def _on_file_loaded(event):
            self._is_loaded = True
            # Cache fps now that the file is ready
            try:
                v = self._mpv.container_fps
                if v and float(v) > 0:
                    self._fps = float(v)
                else:
                    v = self._mpv.estimated_vf_fps
                    if v and float(v) > 0:
                        self._fps = float(v)
            except Exception:
                pass
            path = self._mpv.path or ""
            self.video_loaded.emit(path)
            log.debug("file-loaded: %s  fps=%.3f", path, self._fps)

        @self._mpv.event_callback("end-file")
        def _on_end_file(event):
            # event.data is MpvEventEndFile; reason 0 = EOF
            try:
                if event.data and event.data.reason == 0:
                    self.end_reached.emit()
            except Exception:
                pass

    # ----------------------------------------------------------------- lifecycle

    def load(self, path: str) -> None:
        self._is_loaded = False
        self._logical_time = 0.0
        self._actual_time = 0.0
        self._duration = 0.0
        self._fps = 0.0
        self._mpv.play(path)
        log.debug("load requested: %s", path)

    def close_video(self) -> None:
        self._mpv.command("stop")
        self._is_loaded = False
        self._logical_time = 0.0
        self._actual_time = 0.0
        self._duration = 0.0

    def shutdown(self) -> None:
        try:
            self._mpv.terminate()
        except Exception:
            pass

    # ----------------------------------------------------------------- transport

    def play(self) -> None:
        self._mpv.pause = False

    def pause(self) -> None:
        self._mpv.pause = True

    def toggle_play(self) -> None:
        self._mpv.command("cycle", "pause")

    def set_paused(self, paused: bool) -> None:
        self._mpv.pause = paused

    # ------------------------------------------------------------------ seeking

    def seek_exact(self, seconds: float) -> None:
        self._logical_time = seconds  # set immediately for jitter-free cursor
        self._mpv.command("seek", seconds, "absolute+exact")

    def seek_relative(self, seconds: float) -> None:
        target = max(0.0, self._logical_time + seconds)
        self._logical_time = target
        self._mpv.command("seek", seconds, "relative+exact")

    def seek_percent(self, fraction: float) -> None:
        self.seek_exact(fraction * self._duration)

    def step_frame(self, forward: bool = True) -> None:
        if forward:
            self._mpv.command("frame-step")
        else:
            self._mpv.command("frame-back-step")
        # logical_time will be updated by the time-pos observer once mpv steps

    # ---------------------------------------------------------------- rate/audio

    def set_speed(self, speed: float) -> None:
        self._mpv.speed = speed

    def set_volume(self, volume: float) -> None:
        self._mpv.volume = volume

    def mute(self) -> None:
        self._mpv.mute = True

    def unmute(self) -> None:
        self._mpv.mute = False

    # -------------------------------------------------------------------- state

    @property
    def logical_time(self) -> float:
        return self._logical_time

    @property
    def actual_time(self) -> float:
        return self._actual_time

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def fps(self) -> float:
        if self._fps > 0:
            return self._fps
        try:
            v = self._mpv.container_fps
            if v and float(v) > 0:
                return float(v)
            v = self._mpv.estimated_vf_fps
            if v and float(v) > 0:
                return float(v)
        except Exception:
            pass
        return 0.0

    @property
    def frame_time(self) -> float:
        f = self.fps
        return 1.0 / f if f > 0 else 0.0

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @property
    def video_size(self) -> tuple[int, int]:
        try:
            w = self._mpv.dwidth
            h = self._mpv.dheight
            if w and h:
                return (int(w), int(h))
        except Exception:
            pass
        return (0, 0)

    @property
    def speed(self) -> float:
        return self._speed
