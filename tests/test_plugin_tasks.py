"""Tests for the plugin async-task primitive (run_async / TaskRunner)."""
from __future__ import annotations

import sys
import threading
import time
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from PySide6.QtCore import QThreadPool  # noqa: E402

from wombat.plugins.api import PluginContext  # noqa: E402
from wombat.plugins.tasks import TaskReport, TaskRunner  # noqa: E402

MAIN_IDENT = threading.get_ident()


def _pump_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        QThreadPool.globalInstance().waitForDone(20)
        _app.processEvents()
    _app.processEvents()
    return predicate()


# ------------------------------------------------------------------ basics

def test_run_async_delivers_result():
    runner = TaskRunner()
    got = []
    runner.run_async(lambda report: 6 * 7, on_done=got.append)
    assert _pump_until(lambda: got)
    assert got == [42]
    assert runner.active_count == 0  # retired after completion


def test_work_runs_off_gui_thread_but_callback_on_gui_thread():
    runner = TaskRunner()
    idents: dict[str, int] = {}

    def work(report: TaskReport) -> int:
        idents["work"] = threading.get_ident()
        return 1

    def done(_result) -> None:
        idents["done"] = threading.get_ident()

    runner.run_async(work, on_done=done)
    assert _pump_until(lambda: "done" in idents)
    assert idents["work"] != MAIN_IDENT      # ran on a worker
    assert idents["done"] == MAIN_IDENT      # delivered on the GUI thread


def test_error_routed_to_on_error():
    runner = TaskRunner()
    errors = []

    def boom(report: TaskReport):
        raise ValueError("nope")

    runner.run_async(boom, on_error=errors.append)
    assert _pump_until(lambda: errors)
    assert isinstance(errors[0], ValueError)


def test_progress_reported():
    runner = TaskRunner()
    progress: list[tuple[float, str]] = []

    def work(report: TaskReport):
        report.progress(0.5, "half")
        report.progress(1.0, "done")
        return None

    runner.run_async(work, on_progress=lambda f, m: progress.append((f, m)))
    assert _pump_until(lambda: len(progress) >= 2)
    assert progress == [(0.5, "half"), (1.0, "done")]


# ------------------------------------------------------------------ cancellation

def test_cancel_is_seen_and_suppresses_on_done():
    runner = TaskRunner()
    started = threading.Event()
    release = threading.Event()
    seen_cancel: list[bool] = []
    done_called: list[int] = []

    def work(report: TaskReport):
        started.set()
        release.wait(2.0)
        seen_cancel.append(report.cancelled)
        return "result"

    handle = runner.run_async(work, on_done=lambda r: done_called.append(1))
    assert started.wait(2.0)       # worker is running
    handle.cancel()
    release.set()                  # let it finish
    assert _pump_until(lambda: seen_cancel and runner.active_count == 0)
    assert seen_cancel == [True]
    assert done_called == []       # cancelled → on_done suppressed


def test_context_teardown_cancels_outstanding():
    ctx = PluginContext("t", MagicMock(), MagicMock())
    started = threading.Event()
    release = threading.Event()
    seen_cancel: list[bool] = []

    def work(report: TaskReport):
        started.set()
        release.wait(2.0)
        seen_cancel.append(report.cancelled)
        return None

    ctx.run_async(work)
    assert started.wait(2.0)
    ctx._teardown()                # host disabling the plugin
    release.set()
    assert _pump_until(lambda: seen_cancel)
    assert seen_cancel == [True]
