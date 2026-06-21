"""Tests for the Plugin Log panel and its thread-safe logging bridge."""
from __future__ import annotations

import logging
import sys
import threading
import time

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.plugins.api import PluginLog  # noqa: E402
from wombat.ui.plugin_log_panel import PLUGIN_LOGGER_NAME, PluginLogPanel  # noqa: E402


def _pump_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.005)
    _app.processEvents()
    return predicate()


def test_panel_shows_plugin_log_record():
    panel = PluginLogPanel()
    try:
        PluginLog("demo").info("hello from plugin")
        assert _pump_until(lambda: "hello from plugin" in panel._view.toPlainText())  # noqa: SLF001
        assert "wombat.plugin.demo" in panel._view.toPlainText()  # noqa: SLF001
    finally:
        panel.detach()


def test_panel_receives_record_from_worker_thread():
    panel = PluginLogPanel()
    try:
        def worker():
            logging.getLogger(f"{PLUGIN_LOGGER_NAME}.bg").warning("from a thread")

        t = threading.Thread(target=worker)
        t.start()
        t.join(2.0)
        assert _pump_until(lambda: "from a thread" in panel._view.toPlainText())  # noqa: SLF001
    finally:
        panel.detach()


def test_detach_removes_handler():
    panel = PluginLogPanel()
    panel.detach()
    before = panel._view.toPlainText()  # noqa: SLF001
    PluginLog("after").info("should not appear")
    _pump_until(lambda: False, timeout_s=0.2)
    assert panel._view.toPlainText() == before  # noqa: SLF001
