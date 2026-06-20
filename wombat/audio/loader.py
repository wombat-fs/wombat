"""WaveformLoader — background QThread worker for audio extraction.

The worker blocks inside a synchronous ``subprocess`` call (ffmpeg), so it can
NOT be interrupted by ``QThread.quit()`` and waiting on it would freeze the GUI
for the full decode time.  ``cancel()`` therefore *detaches* the in-flight run
(ignores its result) rather than trying to stop it, and every running
``QThread`` plus its worker is kept in ``_live`` so neither is garbage-collected
while still running — dropping the worker's last ref mid-run gets it collected
underfoot and crashes with "QThread: Destroyed while thread is still running".
"""
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
    ``None`` if extraction failed / no audio).  Calling ``load()`` again while a
    previous run is in flight abandons that run's result and starts a new one;
    the abandoned thread is left to finish and clean itself up.
    """

    waveform_ready = Signal(object)   # WaveformData | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active: _Worker | None = None         # the run whose result we want
        # Strong refs to BOTH thread and worker of every in-flight run — the
        # worker must outlive its run() (it executes there); dropping its last
        # Python ref mid-run gets the C++ object collected and crashes the thread.
        self._live: dict[QThread, _Worker] = {}

    def load(self, video_path: str) -> None:
        self.cancel()
        thread = QThread()
        worker = _Worker(video_path)
        worker.moveToThread(thread)
        self._live[thread] = worker
        self._active = worker

        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Release our strong refs only once the thread has truly finished.
        thread.finished.connect(lambda t=thread: self._live.pop(t, None))

        thread.start()

    def cancel(self) -> None:
        """Abandon the in-flight run's result (non-blocking).

        The worker can't be interrupted mid-subprocess, so we simply stop
        caring about it; it stays referenced in ``_live`` (so it is not
        garbage-collected mid-run) and tears itself down via ``finished`` when
        extraction returns.
        """
        self._active = None

    def wait_all(self, timeout_ms: int = 4000) -> None:
        """Block until running extractions finish — for application shutdown."""
        self._active = None
        for thread in list(self._live):
            if thread.isRunning():
                thread.wait(timeout_ms)

    def _on_done(self, data: object) -> None:
        # Ignore results from runs that were cancelled/superseded.
        if self.sender() is not self._active:
            return
        self._active = None
        self.waveform_ready.emit(data)
