"""PluginLogPanel — shows log output from plugins (the `wombat.plugin.*` loggers).

The OFS analog is "Extensions → Show logs". A plugin's ``ctx.log`` writes to a
logger named ``wombat.plugin.<id>``; this panel attaches a handler to the parent
``wombat.plugin`` logger and renders every record.

Records may arrive from a worker thread (a plugin logging inside ``run_async``),
so the handler never touches widgets directly: it emits a Qt signal that, because
the handler object lives on the GUI thread, is auto-queued onto the GUI event loop.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

PLUGIN_LOGGER_NAME = "wombat.plugin"
_MAX_BLOCKS = 2000   # cap the scrollback so a chatty plugin can't grow unbounded


class _LogSignal(QObject):
    """GUI-thread-affine carrier for a formatted log line."""

    record = Signal(str)


class _QtLogBridge(logging.Handler):
    """Logging handler that forwards formatted records to the GUI thread via a signal.

    Composes a QObject rather than inheriting one, so ``Handler.emit`` doesn't clash
    with Qt's signal machinery. The carrier is created on the GUI thread, so emitting
    from a worker thread is auto-queued onto the GUI event loop.
    """

    def __init__(self) -> None:
        super().__init__()
        self.signal = _LogSignal()
        self.setFormatter(logging.Formatter("%(asctime)s  %(name)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # noqa: BLE001 — logging must never raise into callers
            self.handleError(record)
            return
        self.signal.record.emit(msg)


class PluginLogPanel(QWidget):
    """A read-only scrollback of plugin log output, with a Clear button."""

    appended = Signal()   # emitted after a line is added (useful for tests/auto-raise)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(_MAX_BLOCKS)
        self._view.setPlaceholderText("Plugin log output appears here.")

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._view.clear)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._view, 1)
        layout.addLayout(buttons)

        self._bridge = _QtLogBridge()
        self._bridge.signal.record.connect(self._append)

        self._logger = logging.getLogger(PLUGIN_LOGGER_NAME)
        self._logger.addHandler(self._bridge)
        # Ensure records propagate to our handler even if root level is high.
        if self._logger.level == logging.NOTSET:
            self._logger.setLevel(logging.INFO)

    @Slot(str)
    def _append(self, line: str) -> None:
        self._view.appendPlainText(line)
        self.appended.emit()

    def detach(self) -> None:
        """Remove the logging handler. Call when the panel is destroyed."""
        self._logger.removeHandler(self._bridge)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        self.detach()
        super().closeEvent(event)
