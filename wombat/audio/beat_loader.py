"""BeatDetectionLoader — background QThread worker for beat detection.

Detection runs the external ``beat_this_cpp`` binary (transformer inference),
which is slow, so it must never block the GUI thread.  Mirrors the structure of
``WaveformLoader``; the only extras are ``detection_started`` /
``detection_finished`` signals so the UI can show progress.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

log = logging.getLogger(__name__)


class _Worker(QObject):
    done = Signal(object)   # BeatGrid | None

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        from wombat.audio.beats import detect_beats
        result = detect_beats(self._path)
        self.done.emit(result)


class BeatDetectionLoader(QObject):
    """Detects beats in a video's audio in a background thread.

    Connect ``beats_ready`` to receive the result (``BeatGrid`` or ``None`` if
    the tool is unavailable / detection failed).  ``detection_started`` and
    ``detection_finished`` bracket the run for progress UI.  Calling ``load()``
    again while a previous load is running cancels it first.
    """

    beats_ready = Signal(object)          # BeatGrid | None
    detection_started = Signal()
    detection_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None

    def load(self, video_path: str) -> None:
        self.cancel()
        thread = QThread()
        worker = _Worker(video_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Clear refs only after the thread has actually stopped, preventing
        # premature GC of the QThread while it is still running.
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        self.detection_started.emit()
        thread.start()

    def cancel(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    def _on_done(self, data: object) -> None:
        self.detection_finished.emit()
        self.beats_ready.emit(data)
