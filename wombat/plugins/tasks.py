"""Managed async tasks for plugins — the safe replacement for raw threads.

The contract (see docs/phase-9-plugin-api.md):

  - The work function runs on a ``QThreadPool`` worker. It must NOT touch the
    domain model or any Qt widget.
  - ``on_done`` / ``on_error`` / ``on_progress`` are marshalled to the GUI thread,
    so they MAY call ``ctx.edit`` and update UI. This is the only safe place to
    write results back.
  - The work function receives a :class:`TaskReport`; it should poll
    ``report.cancelled`` and call ``report.progress(frac, msg)`` to drive the
    host's progress UI.

GUI-thread delivery is guaranteed by routing results through a QObject whose
affinity is the GUI thread: the worker emits a signal, and because the receiving
slot lives on the GUI thread, Qt's auto-connection queues it onto the GUI event
loop rather than running it on the worker.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

log = logging.getLogger(__name__)

WorkFn = Callable[["TaskReport"], Any]


class TaskReport:
    """Handed to the work function: cooperative cancellation + progress reporting."""

    __slots__ = ("_cancel", "_signals")

    def __init__(self, cancel: threading.Event, signals: _TaskSignals) -> None:
        self._cancel = cancel
        self._signals = signals

    @property
    def cancelled(self) -> bool:
        """True once the task has been cancelled — poll this in long loops."""
        return self._cancel.is_set()

    def progress(self, fraction: float, message: str = "") -> None:
        """Report progress (0.0–1.0). Delivered to ``on_progress`` on the GUI thread."""
        self._signals.progress.emit(float(fraction), str(message))


class TaskHandle:
    """Returned by ``run_async``. Lets the caller cancel and query a task."""

    __slots__ = ("_cancel", "label")

    def __init__(self, cancel: threading.Event, label: str) -> None:
        self._cancel = cancel
        self.label = label

    def cancel(self) -> None:
        """Request cancellation. The worker stops at its next ``report.cancelled`` check;
        any pending ``on_done`` is suppressed."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class _TaskSignals(QObject):
    """Bridges worker-thread results onto the GUI thread.

    Created on the GUI thread, so the slots below have GUI-thread affinity and the
    worker's cross-thread ``emit`` is auto-queued onto the GUI event loop.
    """

    done = Signal(object)
    failed = Signal(object)
    progress = Signal(float, str)

    def __init__(
        self,
        *,
        cancel: threading.Event,
        on_done: Callable[[Any], None] | None,
        on_error: Callable[[BaseException], None] | None,
        on_progress: Callable[[float, str], None] | None,
        cleanup: Callable[[_TaskSignals], None],
    ) -> None:
        super().__init__()
        self._cancel = cancel
        self._on_done = on_done
        self._on_error = on_error
        self._on_progress = on_progress
        self._cleanup = cleanup
        self.done.connect(self._handle_done)
        self.failed.connect(self._handle_failed)
        self.progress.connect(self._handle_progress)

    @Slot(object)
    def _handle_done(self, result: Any) -> None:
        self._cleanup(self)
        if self._cancel.is_set():
            return  # don't apply a result the caller no longer wants
        if self._on_done is not None:
            self._on_done(result)

    @Slot(object)
    def _handle_failed(self, exc: BaseException) -> None:
        self._cleanup(self)
        if self._on_error is not None:
            self._on_error(exc)
        else:
            log.error("plugin task failed: %s", exc, exc_info=exc)

    @Slot(float, str)
    def _handle_progress(self, fraction: float, message: str) -> None:
        if self._cancel.is_set():
            return
        if self._on_progress is not None:
            self._on_progress(fraction, message)


class _TaskRunnable(QRunnable):
    def __init__(self, fn: WorkFn, report: TaskReport, signals: _TaskSignals) -> None:
        super().__init__()
        self._fn = fn
        self._report = report
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._fn(self._report)
        except BaseException as exc:  # noqa: BLE001 — surfaced via on_error
            self._signals.failed.emit(exc)
            return
        self._signals.done.emit(result)


class TaskRunner:
    """Owns the live tasks for one plugin. Cancels everything on teardown.

    One per PluginContext, so disabling a plugin reliably stops its background work.
    """

    def __init__(self, pool: QThreadPool | None = None) -> None:
        self._pool = pool or QThreadPool.globalInstance()
        # signals → handle for every in-flight task; keeps both alive until done.
        self._live: dict[_TaskSignals, TaskHandle] = {}

    def run_async(
        self,
        fn: WorkFn,
        *,
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        label: str = "",
    ) -> TaskHandle:
        cancel = threading.Event()
        handle = TaskHandle(cancel, label)
        signals = _TaskSignals(
            cancel=cancel,
            on_done=on_done,
            on_error=on_error,
            on_progress=on_progress,
            cleanup=self._retire,
        )
        self._live[signals] = handle
        report = TaskReport(cancel, signals)
        self._pool.start(_TaskRunnable(fn, report, signals))
        return handle

    def cancel_all(self) -> None:
        """Cancel every outstanding task (called on plugin teardown)."""
        for handle in list(self._live.values()):
            handle.cancel()

    @property
    def active_count(self) -> int:
        return len(self._live)

    def _retire(self, signals: _TaskSignals) -> None:
        self._live.pop(signals, None)
