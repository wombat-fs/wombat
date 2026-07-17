"""ScriptingMode — pluggable authoring mode abstraction.

Phase 4: DefaultMode only (straight passthrough to editor.add_action).
Phase 9: AlternatingMode, RecordingMode added here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wombat.app.editor import EditorController
    from wombat.playback.player import VideoPlayer


class ScriptingMode(ABC):
    @abstractmethod
    def add_point(self, editor: EditorController, at: float, pos: int) -> None: ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


class DefaultMode(ScriptingMode):
    def add_point(self, editor: EditorController, at: float, pos: int) -> None:
        editor.add_action(at, pos)


class AlternatingMode(ScriptingMode):
    """Alternates between two fixed positions on each keypress.

    The ``pos`` argument from the caller is ignored; each call flips between
    ``top_pos`` and ``bottom_pos`` automatically.
    """

    def __init__(self, top_pos: int = 100, bottom_pos: int = 0) -> None:
        self._top_pos = top_pos
        self._bottom_pos = bottom_pos
        self._next_is_top = True

    @property
    def name(self) -> str:
        return "Alternating"

    @property
    def top_pos(self) -> int:
        return self._top_pos

    @top_pos.setter
    def top_pos(self, v: int) -> None:
        self._top_pos = max(0, min(100, v))

    @property
    def bottom_pos(self) -> int:
        return self._bottom_pos

    @bottom_pos.setter
    def bottom_pos(self, v: int) -> None:
        self._bottom_pos = max(0, min(100, v))

    def reset(self) -> None:
        """Reset the alternating state so the next call outputs top_pos."""
        self._next_is_top = True

    def add_point(self, editor: EditorController, at: float, pos: int) -> None:
        p = self._top_pos if self._next_is_top else self._bottom_pos
        self._next_is_top = not self._next_is_top
        editor.add_action(at, p)


class RecordingMode(ScriptingMode):
    """Continuous real-time recording mode.

    While recording, a QTimer samples ``current_value`` at ~30 Hz and writes
    it directly into the active layer via ``editor.record_action()`` (no
    per-sample undo entry; the whole recording is one undo step).

    Lifecycle
    ---------
    1. Call ``set_context(editor, player)`` once to wire the editor + player.
    2. Call ``toggle_recording()`` (or bind to a button) to start / stop.
    3. Connect ``recording_changed`` to update the UI.

    The timer stops automatically when playback is paused.
    ``add_point()`` inserts the current value as a manual override while not
    recording, or is a no-op during active recording (the timer handles it).
    """

    def __init__(self) -> None:
        # Signals require a QObject; we use a plain companion object instead
        # so RecordingMode doesn't need to inherit QObject itself.
        self._value: int = 50
        self._recording: bool = False
        self._editor: EditorController | None = None
        self._player: VideoPlayer | None = None
        self._timer_interval_ms: int = 33   # ~30 Hz

        # Lazy-import Qt only when the mode is constructed (i.e. at runtime).
        from PySide6.QtCore import QTimer
        self._timer = QTimer()
        self._timer.setInterval(self._timer_interval_ms)
        self._timer.timeout.connect(self._sample)

    @property
    def name(self) -> str:
        return "Recording"

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def current_value(self) -> int:
        return self._value

    def set_context(self, editor: EditorController, player: VideoPlayer) -> None:
        """Wire the editor and player.  Must be called before ``toggle_recording``."""
        old_player = self._player
        if old_player is not None:
            try:
                old_player.playback_changed.disconnect(self._on_playback_changed)
            except RuntimeError:
                pass
        self._editor = editor
        self._player = player
        if player is not None:
            player.playback_changed.connect(self._on_playback_changed)

    def set_value(self, v: int) -> None:
        """Called by the slider/control when the user moves it."""
        self._value = max(0, min(100, v))

    def toggle_recording(self) -> None:
        if self._recording:
            self._stop(commit=True)
        else:
            self._start()

    def _start(self) -> None:
        if self._editor is None or self._recording:
            return
        self._editor.begin_recording()
        self._recording = True
        self._timer.start()

    def _stop(self, commit: bool = True) -> None:
        if not self._recording:
            return
        self._timer.stop()
        self._recording = False
        if self._editor is not None:
            if commit:
                self._editor.end_recording()
            else:
                self._editor.cancel_recording()

    def _on_playback_changed(self, is_paused: bool) -> None:
        if is_paused and self._recording:
            self._stop(commit=True)

    def _sample(self) -> None:
        if self._editor is not None and self._player is not None:
            t = self._player.logical_time
            self._editor.record_action(t, self._value)

    def add_point(self, editor: EditorController, at: float, pos: int) -> None:
        """Manual override: insert the current slider value at the playhead."""
        if not self._recording:
            editor.add_action(at, self._value)
        # during recording the timer handles everything; ignore manual keypresses

    def deactivate(self) -> None:
        """Called when the user switches away from this mode."""
        if self._recording:
            self._stop(commit=True)
