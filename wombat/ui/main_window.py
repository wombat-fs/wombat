import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
)

from wombat.settings import AppSettings

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._settings = AppSettings()
        self.setWindowTitle("Wombat")
        self.setMinimumSize(900, 600)

        self._build_central()
        self._build_docks()
        self._build_menus()
        self._restore_state()

    # ------------------------------------------------------------------ layout

    def _build_central(self) -> None:
        placeholder = QLabel("Video — coming in Phase 1")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #888; font-size: 18px;")
        self.setCentralWidget(placeholder)

    def _build_docks(self) -> None:
        self._timeline_dock = self._make_dock(
            "Timeline",
            "timelineDock",
            "Timeline — coming in Phase 3",
            Qt.DockWidgetArea.BottomDockWidgetArea,
        )
        self._channels_dock = self._make_dock(
            "Channels / Layers",
            "channelsDock",
            "Channels / Layers — coming in Phases 5–6",
            Qt.DockWidgetArea.RightDockWidgetArea,
        )

    def _make_dock(
        self,
        title: str,
        object_name: str,
        placeholder_text: str,
        area: Qt.DockWidgetArea,
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        label = QLabel(placeholder_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888;")
        dock.setWidget(label)
        self.addDockWidget(area, dock)
        return dock

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")
        file_menu.addAction("Open Media…").setEnabled(False)
        file_menu.addAction("Open Funscript…").setEnabled(False)
        file_menu.addAction("Save Project").setEnabled(False)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("&Quit")
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)

        # Edit
        edit_menu = mb.addMenu("&Edit")
        edit_menu.addAction("Undo").setEnabled(False)
        edit_menu.addAction("Redo").setEnabled(False)

        # View
        view_menu = mb.addMenu("&View")
        view_menu.addAction(self._timeline_dock.toggleViewAction())
        view_menu.addAction(self._channels_dock.toggleViewAction())

        # Help
        help_menu = mb.addMenu("&Help")
        about_action = help_menu.addAction("About Wombat")
        about_action.triggered.connect(self._show_about)

    # ---------------------------------------------------------------- geometry

    def _restore_state(self) -> None:
        geom = self._settings.load_geometry()
        if geom:
            self.restoreGeometry(geom)
        state = self._settings.load_dock_state()
        if state:
            self.restoreState(state)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._settings.save_geometry(self.saveGeometry())
        self._settings.save_dock_state(self.saveState())
        super().closeEvent(event)

    # ----------------------------------------------------------------- actions

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Wombat",
            "<b>Wombat</b><br>"
            "Cross-platform funscript authoring and editing tool.<br><br>"
            "Version 0.1.0 — Phase 0 scaffold",
        )
