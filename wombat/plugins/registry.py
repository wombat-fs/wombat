"""CommandRegistry — plugin-contributed commands for menus and keybindings.

A plugin registers commands in ``on_load`` via ``ctx.register_command(...)``. The
host (MainWindow) owns one shared CommandRegistry, listens to its ``changed``
signal to (re)build the Plugins menu, and binds each command's ``default_key`` (a
Qt key sequence string) through the central keybinding system.

Command ids are namespaced ``<plugin_id>.<local_id>`` so two plugins can use the
same local name. Handlers run on the GUI thread; invocation is error-isolated so a
throwing handler logs to the plugin's log instead of crashing the host.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginCommand:
    plugin_id: str
    local_id: str
    title: str
    handler: Callable[[], None]
    default_key: str | None = None

    @property
    def id(self) -> str:
        """Namespaced command id, e.g. ``motion_assist.generate``."""
        return f"{self.plugin_id}.{self.local_id}"


class CommandRegistry(QObject):
    """Live set of plugin commands. The host rebuilds its Plugins menu on ``changed``."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._commands: dict[str, PluginCommand] = {}

    def add(self, command: PluginCommand) -> None:
        self._commands[command.id] = command
        self.changed.emit()

    def remove_plugin(self, plugin_id: str) -> None:
        """Drop every command contributed by ``plugin_id`` (called on unload)."""
        removed = [cid for cid, c in self._commands.items() if c.plugin_id == plugin_id]
        for cid in removed:
            del self._commands[cid]
        if removed:
            self.changed.emit()

    def commands(self) -> list[PluginCommand]:
        return list(self._commands.values())

    def commands_for(self, plugin_id: str) -> list[PluginCommand]:
        return [c for c in self._commands.values() if c.plugin_id == plugin_id]

    def get(self, command_id: str) -> PluginCommand | None:
        return self._commands.get(command_id)

    def run(self, command_id: str) -> None:
        """Invoke a command's handler with error isolation (on the GUI thread)."""
        cmd = self._commands.get(command_id)
        if cmd is None:
            log.warning("run(%r): no such command", command_id)
            return
        try:
            cmd.handler()
        except Exception as exc:  # noqa: BLE001 — error boundary
            logging.getLogger(f"wombat.plugin.{cmd.plugin_id}").error(
                "command %r failed: %s", cmd.local_id, exc, exc_info=exc
            )
