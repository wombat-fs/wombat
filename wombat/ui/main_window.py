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
from wombat.app.project import Project
from wombat.app.undo import UndoStack
from wombat.domain.funscript_io import FunscriptError
from wombat.playback.player import VideoPlayer
from wombat.settings import AppSettings
from wombat.ui.channels_panel import ChannelsPanel
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
        self._undo = UndoStack()
        self._project = Project.new()
        self._editor = EditorController(self._project, self._player, self._undo)

        self._build_central()
        self._build_docks()
        self._build_menus()
        self._restore_state()

        # Project signals
        self._project.channels_changed.connect(self._on_channels_changed)
        self._project.active_changed.connect(self._on_active_changed)
        self._project.channels_changed.connect(self._mark_dirty)

        # Editor / player signals
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
        self._timeline.set_project(self._project)

        timeline_dock = QDockWidget("Timeline", self)
        timeline_dock.setObjectName("timelineDock")
        timeline_dock.setWidget(self._timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, timeline_dock)
        self._timeline_dock = timeline_dock

        self._channels_panel = ChannelsPanel(self._project)
        channels_dock = QDockWidget("Channels / Layers", self)
        channels_dock.setObjectName("channelsDock")
        channels_dock.setWidget(self._channels_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, channels_dock)
        self._channels_dock = channels_dock

    def _build_menus(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")

        new_action = file_menu.addAction("New Project")
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_project)

        open_project_action = file_menu.addAction("Open Project…")
        open_project_action.setShortcut("Ctrl+O")
        open_project_action.triggered.connect(self._open_project)

        open_media_action = file_menu.addAction("Open Media…")
        open_media_action.setShortcut("Ctrl+Shift+O")
        open_media_action.triggered.connect(self._open_media)

        file_menu.addSeparator()

        import_fs_action = file_menu.addAction("Import Funscript…")
        import_fs_action.triggered.connect(self._import_funscript)

        file_menu.addSeparator()

        self._save_action = file_menu.addAction("Save Project")
        self._save_action.setShortcut("Ctrl+S")
        self._save_action.triggered.connect(self._save_project)

        self._save_as_action = file_menu.addAction("Save Project As…")
        self._save_as_action.setShortcut("Ctrl+Shift+S")
        self._save_as_action.triggered.connect(self._save_project_as)

        export_action = file_menu.addAction("Export Funscripts…")
        export_action.triggered.connect(self._export_funscripts)

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
        if self._project.has_unsaved_edits() and not self._confirm_discard():
            event.ignore()
            return
        offset, vt = self._timeline.get_view_state()
        self._project.view.offset = offset
        self._project.view.visible_time = vt
        self._settings.save_geometry(self.saveGeometry())
        self._settings.save_dock_state(self.saveState())
        self._mpv_widget.closeEvent(event)
        self._player.shutdown()
        super().closeEvent(event)

    # ----------------------------------------------------------------- project lifecycle

    def _set_project(self, project: Project) -> None:
        """Swap in a new project, rewiring all signals and widgets."""
        try:
            self._project.channels_changed.disconnect(self._on_channels_changed)
            self._project.active_changed.disconnect(self._on_active_changed)
            self._project.channels_changed.disconnect(self._mark_dirty)
        except RuntimeError:
            pass

        self._project = project
        self._undo._undo.clear()
        self._undo._redo.clear()

        self._editor.set_project(project)
        self._timeline.set_project(project)
        self._channels_panel.set_project(project)

        project.channels_changed.connect(self._on_channels_changed)
        project.active_changed.connect(self._on_active_changed)
        project.channels_changed.connect(self._mark_dirty)

        self._update_title()
        self._update_edit_menu()

    @Slot()
    def _new_project(self) -> None:
        if self._project.has_unsaved_edits() and not self._confirm_discard():
            return
        self._set_project(Project.new())
        log.info("New project created")

    @Slot()
    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            "",
            "Wombat Projects (*.wombat);;All Files (*)",
        )
        if path:
            if self._project.has_unsaved_edits() and not self._confirm_discard():
                return
            self._load_project(path)

    def _load_project(self, path: str) -> None:
        try:
            proj = Project.load(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Open Project", str(exc))
            return
        self._set_project(proj)
        # Restore per-project view state
        self._timeline.restore_view_state(proj.view.offset, proj.view.visible_time)
        # Sync editor to project's active channel
        self._editor.set_active_channel_index(proj.active_index)
        # Load media if the path resolves
        if proj.media_path and Path(proj.media_path).exists():
            self._player.load(proj.media_path)
        self._update_title()
        log.info("Loaded project: %s", path)

    @Slot()
    def _open_media(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Media",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.wmv *.flv);;All Files (*)",
        )
        if path:
            if self._project.has_unsaved_edits() and not self._confirm_discard():
                return
            self._player.load(path)

    @Slot()
    def _import_funscript(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Funscript",
            "",
            "Funscript Files (*.funscript);;All Files (*)",
        )
        if path:
            try:
                ch = self._project.import_funscript(path)
            except (FunscriptError, OSError) as exc:
                QMessageBox.warning(self, "Import Error", str(exc))
                return
            idx = self._project.channels.index(ch)
            self._project.set_active(idx)
            log.info("Imported funscript: %s", path)

    @Slot()
    def _save_project(self) -> None:
        if self._project.path:
            self._write_project(self._project.path)
        else:
            self._save_project_as()

    @Slot()
    def _save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            self._project.path or "",
            "Wombat Projects (*.wombat);;All Files (*)",
        )
        if path:
            if not path.endswith(".wombat"):
                path += ".wombat"
            self._write_project(path)

    def _write_project(self, path: str) -> None:
        offset, vt = self._timeline.get_view_state()
        self._project.view.offset = offset
        self._project.view.visible_time = vt
        try:
            self._project.save(path)
        except OSError as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        self._update_title()
        log.info("Saved project: %s", path)

    @Slot()
    def _export_funscripts(self) -> None:
        if not self._project.channels:
            QMessageBox.warning(self, "Export", "No channels to export.")
            return
        if self._project.media_path is None:
            QMessageBox.warning(
                self,
                "Export",
                "No media file — cannot determine output filenames.\n"
                "Open a video first.",
            )
            return

        default_dir = str(Path(self._project.media_path).parent)
        out_dir = QFileDialog.getExistingDirectory(
            self, "Export Funscripts To", default_dir
        )
        if not out_dir:
            return

        try:
            written = self._project.export_funscripts(out_dir=out_dir, overwrite=False)
        except FileExistsError as exc:
            resp = QMessageBox.question(
                self,
                "Overwrite?",
                f"File already exists:\n{exc}\n\nOverwrite all?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
            try:
                written = self._project.export_funscripts(out_dir=out_dir, overwrite=True)
            except OSError as exc2:
                QMessageBox.critical(self, "Export Error", str(exc2))
                return
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
            return

        names = "\n".join(Path(p).name for p in written)
        QMessageBox.information(
            self,
            "Export Complete",
            f"Exported {len(written)} file(s):\n{names}",
        )
        log.info("Exported %d funscripts to %s", len(written), out_dir)

    # ----------------------------------------------------------------- slots

    @Slot(str)
    def _on_video_loaded(self, path: str) -> None:
        new_project = Project.new(path)
        self._set_project(new_project)
        self._project.discover_and_load_siblings(path)
        if not self._project.channels:
            self._project.add_channel(Path(path).stem)
        self._project.set_active(0)
        self._editor.set_active_channel_index(0)
        self._project.mark_clean()  # auto-load from media is not an unsaved edit
        self._update_title()
        log.info("Loaded media: %s  (%d channel(s))", path, len(self._project.channels))

    @Slot()
    def _on_channels_changed(self) -> None:
        self._editor.set_active_channel_index(self._project.active_index)
        self._update_edit_menu()

    @Slot(int)
    def _on_active_changed(self, index: int) -> None:
        self._editor.set_active_channel_index(index)

    @Slot()
    def _mark_dirty(self) -> None:
        self._project.mark_dirty()
        self._update_title()

    @Slot()
    def _update_edit_menu(self) -> None:
        self._undo_action.setEnabled(self._editor.can_undo)
        self._redo_action.setEnabled(self._editor.can_redo)

    @Slot(bool)
    def _on_snap_toggled(self, checked: bool) -> None:
        self._editor.snap_to_frame = checked

    def _update_title(self) -> None:
        dirty = " *" if self._project.has_unsaved_edits() else ""
        if self._project.path:
            name = Path(self._project.path).stem
            self.setWindowTitle(f"Wombat — {name}{dirty}")
        elif self._project.media_path:
            name = Path(self._project.media_path).name
            self.setWindowTitle(f"Wombat — {name}{dirty}")
        else:
            self.setWindowTitle(f"Wombat{dirty}")

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
            "Version 0.1.0 — Phase 5 (Multi-channel Project)",
        )
