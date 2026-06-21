"""Tests for PluginsController — the MainWindow plugin wiring."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from PySide6.QtWidgets import QMainWindow, QMenu  # noqa: E402

import wombat.ui.plugins_controller as pc_mod  # noqa: E402
from wombat.plugins.loader import PluginState  # noqa: E402
from wombat.ui.plugins_controller import PluginsController, user_plugins_dir  # noqa: E402


class FakeSettings:
    def __init__(self) -> None:
        self._enabled: list[str] = []

    def load_enabled_plugins(self) -> list[str]:
        return list(self._enabled)

    def save_enabled_plugins(self, ids: list[str]) -> None:
        self._enabled = list(ids)


def _make_plugin(root: Path, pid: str, body: str) -> None:
    d = root / pid
    d.mkdir(parents=True)
    (d / "__init__.py").write_text(textwrap.dedent(body))
    (d / "plugin.toml").write_text(
        textwrap.dedent(
            f"""
            [plugin]
            name = "{pid}"
            id = "{pid}"
            entry = "{pid}:Plugin"
            api = "1"
            """
        )
    )


COMMAND_PLUGIN = """
    from wombat.plugins import WombatPlugin
    from wombat.plugins.ui import IntInput, PanelSpec

    class Plugin(WombatPlugin):
        def on_load(self, ctx):
            self.ran = []
            ctx.register_command("go", "Do It", lambda: self.ran.append(1),
                                 default_key="Ctrl+Shift+G")

        def settings_panel(self):
            return PanelSpec([IntInput("n", "N", value=1)])
"""

FAILING_PLUGIN = """
    from wombat.plugins import WombatPlugin

    class Plugin(WombatPlugin):
        def on_load(self, ctx):
            raise RuntimeError("boom")
"""


@pytest.fixture
def window():
    w = QMainWindow()
    yield w
    w.close()


@pytest.fixture(autouse=True)
def _clean_sys_modules():
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        sys.modules.pop(name, None)


def _controller(window, tmp_path: Path) -> tuple[PluginsController, FakeSettings]:
    settings = FakeSettings()
    ctrl = PluginsController(
        window, MagicMock(), MagicMock(), settings, plugins_dir=tmp_path
    )
    ctrl.install_menu(window.menuBar())
    return ctrl, settings


def _action(menu: QMenu, text: str):
    for a in menu.actions():
        if a.text() == text:
            return a
    raise AssertionError(f"no action {text!r} in {[a.text() for a in menu.actions()]}")


# ------------------------------------------------------------------ tests

def test_user_plugins_dir_is_named_plugins():
    assert user_plugins_dir().name == "plugins"


def test_menu_lists_discovered_plugin(window, tmp_path):
    _make_plugin(tmp_path, "demo", COMMAND_PLUGIN)
    ctrl, _ = _controller(window, tmp_path)
    act = _action(ctrl._menu, "demo")
    assert act.isCheckable() and not act.isChecked()


def test_empty_dir_shows_placeholder(window, tmp_path):
    ctrl, _ = _controller(window, tmp_path)
    labels = [a.text() for a in ctrl._menu.actions()]
    assert "No plugins installed" in labels


def test_enable_adds_command_and_settings_dock(window, tmp_path):
    _make_plugin(tmp_path, "demo", COMMAND_PLUGIN)
    ctrl, settings = _controller(window, tmp_path)

    _action(ctrl._menu, "demo").setChecked(True)   # enable

    lp = ctrl._manager.get("demo")
    assert lp.state == PluginState.ENABLED
    assert settings.load_enabled_plugins() == ["demo"]
    # command surfaced in the Commands submenu
    cmd_action = _action(ctrl._commands_menu, "Do It")
    assert cmd_action.shortcut().toString() == "Ctrl+Shift+G"
    # settings dock created
    assert "demo" in ctrl._settings_docks
    # triggering the command runs the plugin handler
    cmd_action.trigger()
    assert lp.instance.ran == [1]


def test_disable_removes_command_and_dock(window, tmp_path):
    _make_plugin(tmp_path, "demo", COMMAND_PLUGIN)
    ctrl, settings = _controller(window, tmp_path)
    act = _action(ctrl._menu, "demo")
    act.setChecked(True)
    assert ctrl._commands_menu.isEnabled()

    act.setChecked(False)   # disable
    assert ctrl._manager.get("demo").state == PluginState.DISABLED
    assert "demo" not in ctrl._settings_docks
    assert settings.load_enabled_plugins() == []
    # Commands submenu falls back to the disabled placeholder
    assert not ctrl._commands_menu.isEnabled()


def test_restore_enabled_reenables_persisted(window, tmp_path):
    _make_plugin(tmp_path, "demo", COMMAND_PLUGIN)
    ctrl, settings = _controller(window, tmp_path)
    settings._enabled = ["demo"]
    ctrl.restore_enabled()
    assert ctrl._manager.get("demo").state == PluginState.ENABLED
    assert _action(ctrl._menu, "demo").isChecked()


def test_errored_plugin_warns_and_unchecks(window, tmp_path, monkeypatch):
    _make_plugin(tmp_path, "bad", FAILING_PLUGIN)
    warned: list[tuple] = []
    monkeypatch.setattr(pc_mod.QMessageBox, "warning", lambda *a, **k: warned.append(a))
    ctrl, settings = _controller(window, tmp_path)

    _action(ctrl._menu, "bad").setChecked(True)

    assert ctrl._manager.get("bad").state == PluginState.ERRORED
    assert warned                       # user was told
    assert not _action(ctrl._menu, "bad").isChecked()   # reverted
    assert "bad" not in ctrl._settings_docks
    assert settings.load_enabled_plugins() == []


def test_shutdown_disables_all(window, tmp_path):
    _make_plugin(tmp_path, "demo", COMMAND_PLUGIN)
    ctrl, _ = _controller(window, tmp_path)
    _action(ctrl._menu, "demo").setChecked(True)
    assert ctrl._manager.enabled_ids == ["demo"]
    ctrl.shutdown()
    assert ctrl._manager.enabled_ids == []
