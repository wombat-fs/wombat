import logging
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from wombat.app.editor import EditorController
from wombat.app.session import Session
from wombat.app.undo import UndoStack
from wombat.domain.action import ActionList
from wombat.domain.channel import Channel, Layer
from wombat.domain.funscript_io import FunscriptError, load_funscript, save_funscript
from wombat.playback.player import VideoPlayer
from wombat.settings import AppSettings
from wombat.ui.mpv_widget import MpvWidget
from wombat.ui.timeline.timeline_widget import TimelineWidget
from wombat.ui.transport import TransportBar

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._settings = AppSettings()
        self.setWindowTitle("Wombat")
        self.setMinimumSize(900, 600)

        self._player = VideoPlayer()
        self._session = Session(player=self._player)
        self._undo = UndoStack()
        self._editor = EditorController(self._session, self._undo)
        self._unsaved: bool = False
        self._save_path: str | None = None

        self._build_central()
        self._build_docks()
        self._build_menus()
        self._restore_state()

        self._player.video_loaded.connect(self._on_video_loaded)
        self._editor.actions_changed.connect(self._mark_dirty)
        self._editor.history_changed.connect(self._update_edit_menu)

    # ------------------------------------------------------------------ layout

    def _build_central(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._mpv_widget = MpvWidget(self._player.mpv)
        self._transport = TransportBar(self._player)

        layout.addWidget(self._mpv_widget, stretch=1)
        layout.addWidget(self._transport)

        self.setCentralWidget(container)

    def _build_docks(self) -> None:
        self._timeline = TimelineWidget(self._player)
        self._timeline.set_editor(self._editor)

        timeline_dock = QDockWidget("Timeline", self)
        timeline_dock.setObjectName("timelineDock")
        timeline_dock.setWidget(self._timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, timeline_dock)
        self._timeline_dock = timeline_dock

        self._channels_dock = self._make_placeholder_dock(
            "Channels / Layers",
            "channelsDock",
            "Channels / Layers — coming in Phases 5–6",
            Qt.DockWidgetArea.RightDockWidgetArea,
        )

    def _make_placeholder_dock(
        self,
        title: str,
        object_name: str,
        placeholder_text: str,
        area: Qt.DockWidgetArea,
    ) -> QDockWidget:
        from PySide6.QtWidgets import QLabel
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

        file_menu = mb.addMenu("&File")

        new_fs_action = file_menu.addAction("New Funscript")
        new_fs_action.setShortcut("Ctrl+N")
        new_fs_action.triggered.connect(self._new_funscript)

        open_media_action = file_menu.addAction("Open Media…")
        open_media_action.setShortcut("Ctrl+O")
        open_media_action.triggered.connect(self._open_media)

        open_fs_action = file_menu.addAction("Open Funscript…")
        open_fs_action.setShortcut("Ctrl+Shift+O")
        open_fs_action.triggered.connect(self._open_funscript)

        file_menu.addSeparator()

        self._save_action = file_menu.addAction("Save")
        self._save_action.setShortcut("Ctrl+S")
        self._save_action.triggered.connect(self._save)

        self._save_as_action = file_menu.addAction("Save As…")
        self._save_as_action.setShortcut("Ctrl+Shift+S")
        self._save_as_action.triggered.connect(self._save_as)

        file_menu.addSeparator()
        quit_action = file_menu.addAction("&Quit")
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)

        edit_menu = mb.addMenu("&Edit")

        self._undo_action = edit_menu.addAction("Undo")
        self._undo_action.setShortcut("Ctrl+Z")
        self._undo_action.setEnabled(False)
        self._undo_action.triggered.connect(self._editor.undo)

        self._redo_action = edit_menu.addAction("Redo")
        self._redo_action.setShortcut("Ctrl+Y")
        self._redo_action.setEnabled(False)
        self._redo_action.triggered.connect(self._editor.redo)

        edit_menu.addSeparator()

        cut_action = edit_menu.addAction("Cut")
        cut_action.setShortcut("Ctrl+X")
        cut_action.triggered.connect(self._editor.cut)

        copy_action = edit_menu.addAction("Copy")
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self._editor.copy)

        paste_action = edit_menu.addAction("Paste")
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(
            lambda: self._editor.paste(self._player.logical_time)
        )

        select_all_action = edit_menu.addAction("Select All")
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self._editor.select_all)

        view_menu = mb.addMenu("&View")
        view_menu.addAction(self._timeline_dock.toggleViewAction())
        view_menu.addAction(self._channels_dock.toggleViewAction())

        heatmap_action = view_menu.addAction("Heatmap")
        heatmap_action.setCheckable(True)
        heatmap_action.toggled.connect(self._timeline.set_heatmap)

        snap_action = view_menu.addAction("Snap to Frame")
        snap_action.setCheckable(True)
        snap_action.toggled.connect(self._on_snap_toggled)

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
        if self._unsaved and not self._confirm_discard():
            event.ignore()
            return
        self._settings.save_geometry(self.saveGeometry())
        self._settings.save_dock_state(self.saveState())
        self._mpv_widget.closeEvent(event)
        self._player.shutdown()
        super().closeEvent(event)

    # ----------------------------------------------------------------- actions

    @Slot()
    def _new_funscript(self) -> None:
        if self._unsaved and not self._confirm_discard():
            return
        ch = Channel(name="new")
        ch.layers.append(Layer(actions=ActionList()))
        self._session.channels.clear()
        self._session.channels.append(ch)
        self._timeline.set_channels(self._session.channels)
        self._editor.set_active_channel_index(0)
        self._undo._undo.clear()
        self._undo._redo.clear()
        self._unsaved = False
        self._save_path = None
        self._update_title()
        self._update_edit_menu()
        log.info("New funscript created")

    @Slot()
    def _open_media(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Media",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.wmv *.flv);;All Files (*)",
        )
        if path:
            self._player.load(path)

    @Slot()
    def _open_funscript(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Funscript",
            "",
            "Funscript Files (*.funscript);;All Files (*)",
        )
        if path:
            if self._unsaved and not self._confirm_discard():
                return
            self._load_funscript_path(path)

    def _load_funscript_path(self, path: str) -> None:
        try:
            fs = load_funscript(path)
        except (FunscriptError, OSError) as exc:
            QMessageBox.warning(self, "Funscript Error", str(exc))
            return
        name = Path(path).stem
        ch = Channel.from_funscript(fs, name=name)
        self._session.channels.clear()
        self._session.channels.append(ch)
        self._timeline.set_channels(self._session.channels)
        self._editor.set_active_channel_index(0)
        self._undo._undo.clear()
        self._undo._redo.clear()
        self._unsaved = False
        self._save_path = path
        self._update_title()
        self._update_edit_menu()
        log.info("Loaded funscript: %s  (%d actions)", path, len(fs.actions))

    @Slot()
    def _save(self) -> None:
        if self._save_path:
            self._write_funscript(self._save_path)
        else:
            self._save_as()

    @Slot()
    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Funscript",
            self._save_path or "",
            "Funscript Files (*.funscript);;All Files (*)",
        )
        if path:
            if not path.endswith(".funscript"):
                path += ".funscript"
            self._write_funscript(path)

    def _write_funscript(self, path: str) -> None:
        if not self._session.channels:
            QMessageBox.warning(self, "Save", "Nothing to save — no funscript loaded.")
            return
        ch = self._session.channels[0]
        fs = ch.to_funscript()
        try:
            save_funscript(path, fs)
        except OSError as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        self._save_path = path
        self._unsaved = False
        self._update_title()
        log.info("Saved funscript: %s  (%d actions)", path, len(fs.actions))

    @Slot(str)
    def _on_video_loaded(self, path: str) -> None:
        self._update_title()
        log.info("Loaded: %s", path)
        fs_path = Path(path).with_suffix(".funscript")
        if fs_path.exists():
            log.info("Auto-loading funscript: %s", fs_path)
            self._load_funscript_path(str(fs_path))

    @Slot()
    def _mark_dirty(self) -> None:
        self._unsaved = True
        self._update_title()

    @Slot()
    def _update_edit_menu(self) -> None:
        self._undo_action.setEnabled(self._editor.can_undo)
        self._redo_action.setEnabled(self._editor.can_redo)

    @Slot(bool)
    def _on_snap_toggled(self, checked: bool) -> None:
        self._editor.snap_to_frame = checked

    def _update_title(self) -> None:
        video_path = self._player.mpv.path or ""
        base = Path(video_path).name if video_path else "Wombat"
        dirty = " *" if self._unsaved else ""
        self.setWindowTitle(f"Wombat — {base}{dirty}" if video_path else f"Wombat{dirty}")

    def _confirm_discard(self) -> bool:
        resp = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return resp == QMessageBox.StandardButton.Discard

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Wombat",
            "<b>Wombat</b><br>"
            "Cross-platform funscript authoring and editing tool.<br><br>"
            "Version 0.1.0 — Phase 4 (Editing)",
        )
