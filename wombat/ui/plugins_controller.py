"""PluginsController — wires the plugin system into the MainWindow.

Owns the shared CommandRegistry, the PluginManager, the Plugins menu, the Plugin
Log dock, and per-plugin settings docks. Keeps MainWindow thin: construct one,
call ``install_menu`` + ``restore_enabled`` at startup and ``shutdown`` on close.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDockWidget, QMenu, QMenuBar, QMessageBox

from wombat.app.editor import EditorController
from wombat.playback.player import VideoPlayer
from wombat.plugins.api import PluginContext
from wombat.plugins.loader import LoadedPlugin, PluginManager, PluginState
from wombat.plugins.manifest import PluginManifest
from wombat.plugins.registry import CommandRegistry
from wombat.plugins.ui import PanelSpec, build_panel
from wombat.settings import AppSettings
from wombat.ui.plugin_log_panel import PluginLogPanel

log = logging.getLogger(__name__)


def user_plugins_dir() -> Path:
    """The per-user plugins directory (created if missing)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(base or str(Path.home() / ".wombat")) / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


class PluginsController(QObject):
    def __init__(
        self,
        window,
        editor: EditorController,
        player: VideoPlayer,
        settings: AppSettings,
        *,
        plugins_dir: Path | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._editor = editor
        self._player = player
        self._settings = settings

        self._registry = CommandRegistry()
        self._manager = PluginManager(plugins_dir or user_plugins_dir(), self._make_context)
        self._storages: dict[str, dict] = {}
        self._enable_actions: dict[str, QAction] = {}
        self._settings_docks: dict[str, QDockWidget] = {}

        self._log_panel = PluginLogPanel()
        self._log_dock = QDockWidget("Plugin Log", window)
        self._log_dock.setObjectName("pluginLogDock")
        self._log_dock.setWidget(self._log_panel)
        window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self._log_dock.hide()

        self._menu = QMenu("&Plugins", window)
        self._commands_menu: QMenu | None = None
        self._registry.changed.connect(self._rebuild_command_actions)

    # ------------------------------------------------------------------ context

    def _make_context(self, manifest: PluginManifest) -> PluginContext:
        storage = self._storages.setdefault(manifest.id, {})
        return PluginContext(
            manifest.id,
            self._editor,
            self._player,
            storage=storage,
            commands=self._registry,
        )

    # ------------------------------------------------------------------ menu

    def install_menu(self, menu_bar: QMenuBar) -> QMenu:
        """Add the Plugins menu to the menu bar and populate it from disk."""
        menu_bar.addMenu(self._menu)
        self.refresh()
        return self._menu

    def refresh(self) -> None:
        """Re-scan the plugins directory and rebuild the menu."""
        self._manager.discover()
        self._rebuild_menu()

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        self._enable_actions.clear()

        plugins = sorted(self._manager.plugins, key=lambda p: p.manifest.name.lower())
        if not plugins:
            empty = self._menu.addAction("No plugins installed")
            empty.setEnabled(False)
        for lp in plugins:
            act = self._menu.addAction(lp.manifest.name)
            act.setCheckable(True)
            act.setChecked(lp.state == PluginState.ENABLED)
            if lp.state == PluginState.ERRORED and lp.error:
                act.setToolTip(lp.error)
            # Set state before connecting so setChecked above doesn't fire _toggle.
            act.toggled.connect(lambda on, pid=lp.id: self._toggle(pid, on))
            self._enable_actions[lp.id] = act

        self._menu.addSeparator()
        self._commands_menu = self._menu.addMenu("Commands")
        self._rebuild_command_actions()

        self._menu.addSeparator()
        self._menu.addAction(self._log_dock.toggleViewAction())
        rescan = self._menu.addAction("Rescan Plugins")
        rescan.triggered.connect(self.refresh)

    def _rebuild_command_actions(self) -> None:
        menu = self._commands_menu
        if menu is None:
            return
        menu.clear()
        commands = sorted(self._registry.commands(), key=lambda c: c.title.lower())
        if not commands:
            placeholder = menu.addAction("No commands")
            placeholder.setEnabled(False)
            menu.setEnabled(False)
            return
        menu.setEnabled(True)
        for cmd in commands:
            act = menu.addAction(cmd.title)
            if cmd.default_key:
                act.setShortcut(QKeySequence(cmd.default_key))
            act.triggered.connect(lambda _=False, cid=cmd.id: self._registry.run(cid))

    # ------------------------------------------------------------------ enable/disable

    def _toggle(self, plugin_id: str, on: bool) -> None:
        if on:
            lp = self._manager.enable(plugin_id)
            if lp is not None and lp.state == PluginState.ERRORED:
                QMessageBox.warning(
                    self._window, "Plugin Error",
                    f"{lp.manifest.name} failed to enable:\n\n{lp.error}",
                )
                self._set_checked(plugin_id, False)
            elif lp is not None:
                self._add_settings_dock(lp)
        else:
            self._remove_settings_dock(plugin_id)
            self._manager.disable(plugin_id)
        self._persist_enabled()

    def restore_enabled(self) -> None:
        """Enable the plugins the user had on last session (skipping any now missing)."""
        for pid in self._settings.load_enabled_plugins():
            act = self._enable_actions.get(pid)
            if act is not None and not act.isChecked():
                act.setChecked(True)   # fires _toggle → enable

    def shutdown(self) -> None:
        """Disable all plugins and detach the log handler (called on window close)."""
        self._manager.disable_all()
        self._log_panel.detach()

    # ------------------------------------------------------------------ settings docks

    def _add_settings_dock(self, lp: LoadedPlugin) -> None:
        if lp.instance is None:
            return
        try:
            spec = lp.instance.settings_panel()
        except Exception as exc:  # noqa: BLE001 — a bad panel must not break enabling
            log.error("plugin %s settings_panel() failed: %s", lp.id, exc, exc_info=exc)
            return
        if not isinstance(spec, PanelSpec):
            return
        dock = QDockWidget(lp.manifest.name, self._window)
        dock.setObjectName(f"pluginSettings_{lp.id}")
        dock.setWidget(build_panel(spec))
        self._window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self._settings_docks[lp.id] = dock

    def _remove_settings_dock(self, plugin_id: str) -> None:
        dock = self._settings_docks.pop(plugin_id, None)
        if dock is not None:
            self._window.removeDockWidget(dock)
            dock.deleteLater()

    # ------------------------------------------------------------------ helpers

    def _set_checked(self, plugin_id: str, checked: bool) -> None:
        act = self._enable_actions.get(plugin_id)
        if act is not None:
            act.blockSignals(True)
            act.setChecked(checked)
            act.blockSignals(False)

    def _persist_enabled(self) -> None:
        self._settings.save_enabled_plugins(self._manager.enabled_ids)
