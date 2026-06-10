"""WaveformLoader — background QThread worker for audio extraction."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

log = logging.getLogger(__name__)


class _Worker(QObject):
    done = Signal(object)   # WaveformData | None

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        from wombat.audio.waveform import extract_waveform
        result = extract_waveform(self._path)
        self.done.emit(result)


class WaveformLoader(QObject):
    """Extracts waveform data in a background thread.

    Connect ``waveform_ready`` to receive the result (``WaveformData`` or
    ``None`` if extraction failed / no audio).  Calling ``load()`` again
    while a previous load is running cancels it first.
    """

    waveform_ready = Signal(object)   # WaveformData | None

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
        self.waveform_ready.emit(data)
