"""Tests for plugin commands (CommandRegistry) and the declarative settings UI."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from PySide6.QtWidgets import (  # noqa: E402
    QCheckBox,
    QComboBox,
    QPushButton,
    QSlider,
    QSpinBox,
)

from wombat.plugins.api import PluginContext  # noqa: E402
from wombat.plugins.registry import CommandRegistry, PluginCommand  # noqa: E402
from wombat.plugins.ui import (  # noqa: E402
    Button,
    Checkbox,
    Combo,
    Group,
    IntInput,
    IntSlider,
    PanelSpec,
    Text,
    build_panel,
)


def _ctx(commands: CommandRegistry | None = None) -> PluginContext:
    return PluginContext("demo", MagicMock(), MagicMock(), commands=commands)


# ------------------------------------------------------------------ registry

def test_command_id_is_namespaced():
    cmd = PluginCommand("motion", "generate", "Generate", lambda: None)
    assert cmd.id == "motion.generate"


def test_registry_add_run_and_changed_signal():
    reg = CommandRegistry()
    fired = []
    reg.changed.connect(lambda: fired.append(1))
    calls = []
    reg.add(PluginCommand("p", "go", "Go", lambda: calls.append(1)))
    assert fired == [1]
    reg.run("p.go")
    assert calls == [1]


def test_registry_run_is_error_isolated():
    reg = CommandRegistry()

    def boom():
        raise ValueError("nope")

    reg.add(PluginCommand("p", "bad", "Bad", boom))
    reg.run("p.bad")          # must not raise
    reg.run("p.missing")      # unknown id is a no-op


def test_registry_remove_plugin():
    reg = CommandRegistry()
    reg.add(PluginCommand("a", "x", "X", lambda: None))
    reg.add(PluginCommand("b", "y", "Y", lambda: None))
    reg.remove_plugin("a")
    assert [c.id for c in reg.commands()] == ["b.y"]


def test_register_command_via_context_and_teardown():
    reg = CommandRegistry()
    ctx = _ctx(reg)
    cid = ctx.register_command("generate", "Generate strokes", lambda: None, default_key="Ctrl+G")
    assert cid == "demo.generate"
    cmds = reg.commands_for("demo")
    assert len(cmds) == 1 and cmds[0].default_key == "Ctrl+G"
    ctx._teardown()
    assert reg.commands_for("demo") == []


# ------------------------------------------------------------------ panel builder

def test_panel_initial_values():
    spec = PanelSpec([
        IntInput("count", "Count", value=3, minimum=0, maximum=10),
        Checkbox("flag", "Enabled", value=True),
        Combo("mode", "Mode", options=["a", "b", "c"], value=1),
        IntSlider("amp", "Amplitude", minimum=0, maximum=100, value=40),
    ])
    w = build_panel(spec)
    assert w.values == {"count": 3, "flag": True, "mode": 1, "amp": 40}


def test_panel_change_reports_value():
    changes: list[tuple[str, object]] = []
    spec = PanelSpec(
        [IntInput("count", "Count", value=0, maximum=100)],
        on_change=lambda k, v: changes.append((k, v)),
    )
    w = build_panel(spec)
    w.findChild(QSpinBox).setValue(7)
    assert w.values["count"] == 7
    assert changes == [("count", 7)]


def test_panel_checkbox_and_combo_and_slider():
    spec = PanelSpec([
        Checkbox("flag", "On", value=False),
        Combo("mode", "Mode", options=["x", "y"], value=0),
        IntSlider("amp", "Amp", minimum=0, maximum=10, value=0),
    ])
    w = build_panel(spec)
    w.findChild(QCheckBox).setChecked(True)
    w.findChild(QComboBox).setCurrentIndex(1)
    w.findChild(QSlider).setValue(5)
    assert w.values == {"flag": True, "mode": 1, "amp": 5}


def test_panel_button_click_isolated():
    clicked = []

    def handler():
        clicked.append(1)
        raise RuntimeError("boom")  # must not crash the UI

    spec = PanelSpec([Button("go", "Go", on_click=handler)])
    w = build_panel(spec)
    w.findChild(QPushButton).click()
    assert clicked == [1]


def test_panel_group_nesting():
    spec = PanelSpec([
        Group("Amplitude", [IntInput("min", "Min", value=2, maximum=100)]),
    ])
    w = build_panel(spec)
    assert w.values == {"min": 2}
    w.findChild(QSpinBox).setValue(9)
    assert w.values["min"] == 9


def test_control_tooltip_kwonly():
    # tooltip is a kw-only field on the base — constructing with it must not break
    # positional args of subclasses.
    spec = PanelSpec([Text("hello", tooltip="a tip")])
    w = build_panel(spec)
    assert w is not None
