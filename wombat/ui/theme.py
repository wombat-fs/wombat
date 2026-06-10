"""Theme helpers — dark / light palette toggle."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    _c = QColor

    p.setColor(QPalette.ColorRole.Window,          _c(37, 37, 37))
    p.setColor(QPalette.ColorRole.WindowText,      _c(220, 220, 220))
    p.setColor(QPalette.ColorRole.Base,            _c(25, 25, 25))
    p.setColor(QPalette.ColorRole.AlternateBase,   _c(45, 45, 45))
    p.setColor(QPalette.ColorRole.ToolTipBase,     _c(28, 28, 28))
    p.setColor(QPalette.ColorRole.ToolTipText,     _c(220, 220, 220))
    p.setColor(QPalette.ColorRole.Text,            _c(220, 220, 220))
    p.setColor(QPalette.ColorRole.Button,          _c(50, 50, 50))
    p.setColor(QPalette.ColorRole.ButtonText,      _c(220, 220, 220))
    p.setColor(QPalette.ColorRole.BrightText,      _c(255, 80, 80))
    p.setColor(QPalette.ColorRole.Link,            _c(42, 130, 218))
    p.setColor(QPalette.ColorRole.Highlight,       _c(42, 130, 218))
    p.setColor(QPalette.ColorRole.HighlightedText, _c(240, 240, 240))

    disabled = QPalette.ColorGroup.Disabled
    p.setColor(disabled, QPalette.ColorRole.Text,       _c(110, 110, 110))
    p.setColor(disabled, QPalette.ColorRole.ButtonText, _c(110, 110, 110))
    p.setColor(disabled, QPalette.ColorRole.WindowText, _c(110, 110, 110))

    app.setPalette(p)


def apply_light_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(QApplication.style().standardPalette())
