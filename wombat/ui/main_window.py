import logging
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

import wombat.keybindings as keybindings
from wombat.app.editor import EditorController
from wombat.app.project import Project
from wombat.app.undo import UndoStack
from wombat.domain.funscript_io import FunscriptError
from wombat.playback.player import VideoPlayer
from wombat.settings import AppSettings
from wombat.app.autobackup import AutoBackupManager
from wombat.audio.loader import WaveformLoader
from wombat.ui.chapters_panel import ChaptersPanel
from wombat.ui.channels_panel import ChannelsPanel
from wombat.ui.device_simulator import SimulatorOverlay
from wombat.ui.events_panel import EventsPanel
from wombat.ui.mpv_widget import MpvWidget
from wombat.ui.preferences_dialog import PreferencesDialog
from wombat.ui.scripting import AlternatingMode, DefaultMode, RecordingMode, ScriptingMode
from wombat.ui.scripting.recording_panel import RecordingPanel
from wombat.ui.snippet_panel import SnippetPanel
from wombat.ui.timeline.timeline_widget import TimelineWidget
from wombat.ui.transport import TransportBar

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._settings = AppSettings()
        self.setWindowTitle("Wombat")
        self.setMinimumSize(900, 600)

        self._kb = keybindings.load()

        self._player = VideoPlayer()
        self._undo = UndoStack()
        self._project = Project.new()
        self._editor = EditorController(self._project, self._player, self._undo)
        self._loading_project: bool = False  # suppress _on_video_loaded during project load

        # Scripting modes — one shared RecordingMode instance; active mode starts as Default
        self._recording_mode = RecordingMode()
        self._alternating_mode = AlternatingMode()
        self._mode: ScriptingMode = DefaultMode()
        self._recording_mode.set_context(self._editor, self._player)

        self._backup = AutoBackupManager()
        self._waveform_loader = WaveformLoader(self)

        self._build_central()
        self._build_docks()
        self._build_menus()
        self._build_playback_shortcuts()
        self._restore_state()
        self._apply_stored_prefs()
        self._check_recovery()
        self._backup.start(lambda: self._project)

        # Project signals
        self._project.channels_changed.connect(self._on_channels_changed)
        self._project.active_changed.connect(self._on_active_changed)
        self._project.channels_changed.connect(self._mark_dirty)

        # Editor / player signals
        self._player.video_loaded.connect(self._on_video_loaded)
        self._editor.actions_changed.connect(self._mark_dirty)
        self._editor.layer_structure_changed.connect(self._mark_dirty)
        self._editor.history_changed.connect(self._update_edit_menu)

        # Waveform loader
        self._player.video_loaded.connect(self._on_video_loaded_waveform)
        self._waveform_loader.waveform_ready.connect(self._timeline.set_waveform)

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

        # Transparent overlay lives inside the mpv widget and covers it fully.
        # An event filter on the mpv widget keeps the overlay geometry in sync.
        self._simulator = SimulatorOverlay(self._player, self._project, self._mpv_widget)
        self._simulator.setGeometry(self._mpv_widget.rect())
        self._mpv_widget.installEventFilter(self)

    def _build_docks(self) -> None:
        self._timeline = TimelineWidget(self._player)
        self._timeline.set_editor(self._editor)
        self._timeline.set_project(self._project)

        timeline_dock = QDockWidget("Timeline", self)
        timeline_dock.setObjectName("timelineDock")
        timeline_dock.setWidget(self._timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, timeline_dock)
        self._timeline_dock = timeline_dock

        self._channels_panel = ChannelsPanel(self._project, editor=self._editor)
        channels_dock = QDockWidget("Channels / Layers", self)
        channels_dock.setObjectName("channelsDock")
        channels_dock.setWidget(self._channels_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, channels_dock)
        self._channels_dock = channels_dock

        self._snippet_panel = SnippetPanel(self._editor, self._player)
        snippets_dock = QDockWidget("Snippets", self)
        snippets_dock.setObjectName("snippetsDock")
        snippets_dock.setWidget(self._snippet_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, snippets_dock)
        self._snippets_dock = snippets_dock
        self.tabifyDockWidget(channels_dock, snippets_dock)

        self._events_panel = EventsPanel(self._editor)
        events_dock = QDockWidget("Events", self)
        events_dock.setObjectName("eventsDock")
        events_dock.setWidget(self._events_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, events_dock)
        self._events_dock = events_dock
        self.tabifyDockWidget(snippets_dock, events_dock)

        # Sync playhead position to events panel start time
        self._player.position_changed.connect(self._events_panel.sync_playhead)

        self._chapters_panel = ChaptersPanel(self._project, self._player)
        chapters_dock = QDockWidget("Chapters", self)
        chapters_dock.setObjectName("chaptersDock")
        chapters_dock.setWidget(self._chapters_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, chapters_dock)
        self._chapters_dock = chapters_dock
        self.tabifyDockWidget(events_dock, chapters_dock)

        # Recording panel — visible only when RecordingMode is active
        self._recording_panel = RecordingPanel(self._recording_mode)
        recording_dock = QDockWidget("Recording", self)
        recording_dock.setObjectName("recordingDock")
        recording_dock.setWidget(self._recording_panel)
        recording_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, recording_dock)
        recording_dock.hide()
        self._recording_dock = recording_dock

        # Sync button when auto-stop fires (playback paused mid-recording)
        self._player.playback_changed.connect(
            lambda _: self._recording_panel.sync_recording_state()
        )

    def _build_menus(self) -> None:
        kb = self._kb
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")

        new_action = file_menu.addAction("New Project")
        new_action.setShortcut(kb["new_project"])
        new_action.triggered.connect(self._new_project)

        open_project_action = file_menu.addAction("Open Project…")
        open_project_action.setShortcut(kb["open_project"])
        open_project_action.triggered.connect(self._open_project)

        open_media_action = file_menu.addAction("Open Media…")
        open_media_action.setShortcut(kb["open_media"])
        open_media_action.triggered.connect(self._open_media)

        file_menu.addSeparator()

        import_fs_action = file_menu.addAction("Import Funscript…")
        import_fs_action.triggered.connect(self._import_funscript)

        file_menu.addSeparator()

        self._save_action = file_menu.addAction("Save Project")
        self._save_action.setShortcut(kb["save"])
        self._save_action.triggered.connect(self._save_project)

        self._save_as_action = file_menu.addAction("Save Project As…")
        self._save_as_action.setShortcut(kb["save_as"])
        self._save_as_action.triggered.connect(self._save_project_as)

        export_action = file_menu.addAction("Export Funscripts…")
        export_action.setShortcut(kb["export"])
        export_action.triggered.connect(self._export_funscripts)

        file_menu.addSeparator()
        quit_action = file_menu.addAction("&Quit")
        quit_action.setShortcut(kb["quit"])
        quit_action.triggered.connect(self.close)

        edit_menu = mb.addMenu("&Edit")

        self._undo_action = edit_menu.addAction("Undo")
        self._undo_action.setShortcut(kb["undo"])
        self._undo_action.setEnabled(False)
        self._undo_action.triggered.connect(self._editor.undo)

        self._redo_action = edit_menu.addAction("Redo")
        self._redo_action.setShortcut(kb["redo"])
        self._redo_action.setEnabled(False)
        self._redo_action.triggered.connect(self._editor.redo)

        edit_menu.addSeparator()

        cut_action = edit_menu.addAction("Cut")
        cut_action.setShortcut(kb["cut"])
        cut_action.triggered.connect(self._editor.cut)

        copy_action = edit_menu.addAction("Copy")
        copy_action.setShortcut(kb["copy"])
        copy_action.triggered.connect(self._editor.copy)

        paste_action = edit_menu.addAction("Paste")
        paste_action.setShortcut(kb["paste"])
        paste_action.triggered.connect(
            lambda: self._editor.paste(self._player.logical_time)
        )

        select_all_action = edit_menu.addAction("Select All")
        select_all_action.setShortcut(kb["select_all"])
        select_all_action.triggered.connect(self._editor.select_all)

        delete_action = edit_menu.addAction("Delete")
        delete_action.setShortcut(kb["delete"])
        delete_action.triggered.connect(self._editor.remove_selection)

        edit_menu.addSeparator()

        metadata_action = edit_menu.addAction("Channel Metadata…")
        metadata_action.setToolTip("Edit export metadata for the active channel")
        metadata_action.triggered.connect(self._show_metadata)

        edit_menu.addSeparator()

        prefs_action = edit_menu.addAction("Preferences…")
        prefs_action.triggered.connect(self._show_preferences)

        scripting_menu = mb.addMenu("&Scripting")

        from PySide6.QtGui import QActionGroup
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        self._mode_default_action = scripting_menu.addAction("Default Mode")
        self._mode_default_action.setCheckable(True)
        self._mode_default_action.setChecked(True)
        self._mode_default_action.setToolTip("Normal point-insertion mode")
        mode_group.addAction(self._mode_default_action)
        self._mode_default_action.triggered.connect(
            lambda: self._set_mode("default")
        )

        self._mode_alternating_action = scripting_menu.addAction("Alternating Mode")
        self._mode_alternating_action.setCheckable(True)
        self._mode_alternating_action.setToolTip(
            "Auto-alternates between top (100) and bottom (0) positions on each keypress"
        )
        mode_group.addAction(self._mode_alternating_action)
        self._mode_alternating_action.triggered.connect(
            lambda: self._set_mode("alternating")
        )

        self._mode_recording_action = scripting_menu.addAction("Recording Mode")
        self._mode_recording_action.setCheckable(True)
        self._mode_recording_action.setToolTip(
            "Capture slider position in real time during playback"
        )
        mode_group.addAction(self._mode_recording_action)
        self._mode_recording_action.triggered.connect(
            lambda: self._set_mode("recording")
        )

        scripting_menu.addSeparator()

        reset_alt_action = scripting_menu.addAction("Reset Alternating")
        reset_alt_action.setToolTip("Reset alternating state so next keypress inserts top position")
        reset_alt_action.triggered.connect(self._alternating_mode.reset)

        view_menu = mb.addMenu("&View")
        view_menu.addAction(self._timeline_dock.toggleViewAction())
        view_menu.addAction(self._channels_dock.toggleViewAction())
        view_menu.addAction(self._chapters_dock.toggleViewAction())

        sim_action = view_menu.addAction("Device Simulator")
        sim_action.setCheckable(True)
        sim_action.setChecked(True)
        sim_action.toggled.connect(self._simulator.setVisible)

        heatmap_action = view_menu.addAction("Heatmap")
        heatmap_action.setCheckable(True)
        heatmap_action.toggled.connect(self._timeline.set_heatmap)

        waveform_action = view_menu.addAction("Audio Waveform")
        waveform_action.setCheckable(True)
        waveform_action.setChecked(True)
        waveform_action.toggled.connect(self._timeline.set_waveform_visible)

        view_menu.addSeparator()

        self._dark_theme_action = view_menu.addAction("Dark Theme")
        self._dark_theme_action.setCheckable(True)
        self._dark_theme_action.setChecked(self._settings.load_dark_theme())
        self._dark_theme_action.toggled.connect(self._on_theme_toggled)

        view_menu.addSeparator()

        self._snap_action = view_menu.addAction("Snap to Frame")
        self._snap_action.setCheckable(True)
        self._snap_action.toggled.connect(self._on_snap_toggled)

        help_menu = mb.addMenu("&Help")
        about_action = help_menu.addAction("About Wombat")
        about_action.triggered.connect(self._show_about)

    # --------------------------------------------------- playback shortcuts

    def _build_playback_shortcuts(self) -> None:
        """Wire non-menu keyboard shortcuts from the keybinding config."""
        kb = self._kb

        def _sc(key: str, slot) -> None:
            seq = kb.get(key, "")
            if seq:
                QShortcut(QKeySequence(seq), self, slot)

        _sc("play_pause",    self._player.toggle_play)
        _sc("frame_forward", lambda: self._player.step_frame(forward=True))
        _sc("frame_back",    lambda: self._player.step_frame(forward=False))
        _sc("seek_forward",  lambda: self._player.seek_relative(keybindings._SEEK_STEP))
        _sc("seek_back",     lambda: self._player.seek_relative(-keybindings._SEEK_STEP))

        # Chapter navigation: [ = previous, ] = next
        QShortcut(QKeySequence("["), self, self._seek_prev_chapter)
        QShortcut(QKeySequence("]"), self, self._seek_next_chapter)

        # Action-insertion keys (1–9 = pos 10–90, 0 = 100, ` = 0).
        # Guarded: don't fire when a text-input widget has focus.
        action_keys = keybindings.load_action_keys()
        for key_seq, pos in zip(action_keys, keybindings.ACTION_KEY_POSITIONS):
            if key_seq:
                QShortcut(
                    QKeySequence(key_seq), self,
                    lambda p=pos: self._insert_action_at_pos(p),
                )

    def _insert_action_at_pos(self, pos: int) -> None:
        """Route a keypress through the active scripting mode.

        Ignored when a text-editing widget has keyboard focus.
        """
        from PySide6.QtWidgets import QAbstractSpinBox, QLineEdit, QTextEdit
        focused = self.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit, QAbstractSpinBox)):
            return
        self._mode.add_point(self._editor, self._player.logical_time, pos)

    def _set_mode(self, mode_name: str) -> None:
        """Deactivate the current mode and activate the named one."""
        if hasattr(self._mode, "deactivate"):
            self._mode.deactivate()  # type: ignore[union-attr]

        if mode_name == "alternating":
            self._mode = self._alternating_mode
            self._recording_dock.hide()
        elif mode_name == "recording":
            self._mode = self._recording_mode
            self._recording_dock.show()
        else:
            self._mode = DefaultMode()
            self._recording_dock.hide()

        log.debug("Scripting mode: %s", self._mode.name)

    # --------------------------------------------------- preferences

    def _apply_stored_prefs(self) -> None:
        """Apply saved preferences at startup."""
        from wombat.domain.synthesis import set_default_params
        set_default_params(self._settings.get_synthesis_params())

        snap = self._settings.load_snap_to_frame()
        self._editor.snap_to_frame = snap
        self._snap_action.setChecked(snap)

    @Slot()
    def _show_metadata(self) -> None:
        from wombat.ui.metadata_dialog import MetadataDialog
        if not self._editor.has_active_channel:
            return
        ch = self._editor.active_channel
        dlg = MetadataDialog(ch, parent=self)
        if dlg.exec() == MetadataDialog.DialogCode.Accepted:
            self._mark_dirty()

    @Slot(bool)
    def _on_theme_toggled(self, dark: bool) -> None:
        from PySide6.QtWidgets import QApplication
        from wombat.ui.theme import apply_dark_theme, apply_light_theme
        app = QApplication.instance()
        if dark:
            apply_dark_theme(app)
        else:
            apply_light_theme(app)
        self._settings.save_dark_theme(dark)

    @Slot()
    def _seek_prev_chapter(self) -> None:
        ch = self._project.chapter_before(self._player.logical_time)
        if ch is not None:
            self._player.seek_exact(ch.at)

    @Slot()
    def _seek_next_chapter(self) -> None:
        ch = self._project.chapter_after(self._player.logical_time)
        if ch is not None:
            self._player.seek_exact(ch.at)

    def _check_recovery(self) -> None:
        backups = self._backup.find_backups()
        if not backups:
            return
        latest = backups[0]
        resp = QMessageBox.question(
            self,
            "Crash Recovery",
            f"An auto-backup was found from a previous session:\n{latest.name}\n\n"
            "Restore it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp == QMessageBox.StandardButton.Yes:
            self._load_project(str(latest))
        self._backup.clear()

    @Slot()
    def _show_preferences(self) -> None:
        dlg = PreferencesDialog(self._settings, parent=self)
        if dlg.exec() == PreferencesDialog.DialogCode.Accepted:
            self._apply_stored_prefs()
            # Invalidate all channel synthesis caches so new params take effect
            for ch in self._project.channels:
                ch._invalidate_cache()
            self._timeline.update()
            log.info("Preferences saved")

    # ---------------------------------------------------------------- geometry

    def eventFilter(self, obj, ev) -> bool:  # type: ignore[override]
        """Keep the simulator overlay flush with the mpv widget on resize."""
        if obj is self._mpv_widget and ev.type() == QEvent.Type.Resize:
            self._simulator.setGeometry(self._mpv_widget.rect())
        return super().eventFilter(obj, ev)

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
        self._backup.stop()
        self._backup.clear()
        self._waveform_loader.cancel()
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
        self._simulator.set_project(project)
        self._chapters_panel.set_project(project)

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
        # Load media — set flag so _on_video_loaded skips the project-reset path
        if proj.media_path and Path(proj.media_path).exists():
            self._loading_project = True
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
    def _on_video_loaded_waveform(self, path: str) -> None:
        """Trigger background waveform extraction whenever a video is loaded."""
        self._timeline.set_waveform(None)   # clear stale waveform immediately
        self._waveform_loader.load(path)

    @Slot(str)
    def _on_video_loaded(self, path: str) -> None:
        if self._loading_project:
            # Media was loaded as part of opening a project — don't reset the project.
            self._loading_project = False
            self._update_title()
            log.info("Media loaded for project: %s", path)
            return
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
            "Version 0.1.0 — Phase 6 (Layers)",
        )
