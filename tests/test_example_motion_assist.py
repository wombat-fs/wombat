"""Tests for the reference Motion Assist plugin (examples/plugins/motion_assist)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from PySide6.QtCore import QObject, QThreadPool, Signal  # noqa: E402

from wombat.app.editor import EditorController  # noqa: E402
from wombat.app.project import Project  # noqa: E402
from wombat.app.undo import UndoStack  # noqa: E402
from wombat.domain.action import Action, ActionList  # noqa: E402
from wombat.domain.channel import Channel, Layer  # noqa: E402
from wombat.plugins.api import PluginContext  # noqa: E402
from wombat.plugins.loader import PluginManager, PluginState  # noqa: E402

EXAMPLE_PLUGINS = Path(__file__).resolve().parent.parent / "examples" / "plugins"

# Make the example plugin importable directly (for unit-testing its pure functions).
# The loader adds/removes this path itself when enabling; here we keep it for the
# whole module so `import motion_assist` works without going through the loader.
if str(EXAMPLE_PLUGINS) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_PLUGINS))


class FakePlayer(QObject):
    position_changed = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.frame_time = 1.0 / 30.0
        self.logical_time = 0.0
        self.duration = 100.0
        self.fps = 30.0
        self.is_paused = True
        self.mpv = type("M", (), {"path": "/tmp/clip.mp4"})()


class FakeReport:
    cancelled = False

    def progress(self, fraction: float, message: str = "") -> None:
        pass


def _enabled_plugin():
    ch = Channel(name="orig", layers=[Layer(actions=ActionList(), name="base")])
    project = Project.new()
    project.channels.append(ch)
    editor = EditorController(project, FakePlayer(), UndoStack())

    contexts: dict[str, PluginContext] = {}

    def factory(manifest):
        ctx = PluginContext(manifest.id, editor, editor._player)
        contexts[manifest.id] = ctx
        return ctx

    mgr = PluginManager(EXAMPLE_PLUGINS, factory)
    mgr.discover()
    lp = mgr.enable("motion_assist")
    assert lp.state == PluginState.ENABLED, lp.error
    return lp.instance, editor, ch


def _pump_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        QThreadPool.globalInstance().waitForDone(20)
        _app.processEvents()
    _app.processEvents()
    return predicate()


# ------------------------------------------------------------------ generator

def test_generate_actions_pattern():
    from motion_assist import generate_actions

    actions = generate_actions((0.0, 1.0), {"amplitude": 80, "period_ms": 500}, None, FakeReport())
    # half-period = 0.25s over [0, 1] inclusive of the end → t = 0, .25, .5, .75, 1.0
    assert [round(a.at, 3) for a in actions] == [0.0, 0.25, 0.5, 0.75, 1.0]
    # amplitude 80 → lo=10, hi=90, alternating top/bottom
    assert [a.pos for a in actions] == [90, 10, 90, 10, 90]


def test_generate_actions_cancel():
    from motion_assist import generate_actions

    class Cancelled(FakeReport):
        cancelled = True

    params = {"amplitude": 50, "period_ms": 500}
    assert generate_actions((0.0, 10.0), params, None, Cancelled()) is None


# ------------------------------------------------------------------ apply / layer

def test_apply_creates_layer_with_provenance():
    plugin, editor, ch = _enabled_plugin()
    actions = [Action(0.0, 90), Action(0.5, 10)]
    plugin._apply((0.0, 1.0), dict(plugin.cfg), actions)
    assert len(ch.layers) == 2
    layer = ch.layers[-1]
    assert layer.plugin_id == "motion_assist"
    assert layer.name == plugin.LAYER_NAME
    assert [a.pos for a in layer.actions] == [90, 10]


def test_apply_reuses_layer_on_regenerate():
    plugin, editor, ch = _enabled_plugin()
    plugin._apply((0.0, 1.0), dict(plugin.cfg), [Action(0.0, 90)])
    plugin._apply((0.0, 1.0), dict(plugin.cfg), [Action(0.0, 30), Action(0.5, 70)])
    # still exactly one plugin layer, refilled (not a second one)
    plugin_layers = [lay for lay in ch.layers if lay.plugin_id == "motion_assist"]
    assert len(plugin_layers) == 1
    assert [a.pos for a in plugin_layers[0].actions] == [30, 70]


def test_setting_change_regenerates_only_after_first_generate():
    plugin, editor, ch = _enabled_plugin()
    # No layer yet → changing a slider must NOT create one.
    plugin._on_setting_changed("amplitude", 40)
    _pump_until(lambda: False, timeout_s=0.1)
    assert all(lay.plugin_id != "motion_assist" for lay in ch.layers)

    # After a Generate, a setting change regenerates the existing layer.
    plugin._apply((0.0, 1.0), dict(plugin.cfg), [Action(0.0, 90)])
    plugin._on_setting_changed("span_s", 2.0)
    assert _pump_until(
        lambda: len([lay for lay in ch.layers if lay.plugin_id == "motion_assist"]) == 1
    )


# ------------------------------------------------------------------ end-to-end

def test_generate_command_end_to_end():
    plugin, editor, ch = _enabled_plugin()
    plugin.cfg["span_s"] = 1.0
    plugin.generate()   # async: worker computes, on_done writes the layer on GUI thread
    assert _pump_until(lambda: any(lay.plugin_id == "motion_assist" for lay in ch.layers))
    layer = next(lay for lay in ch.layers if lay.plugin_id == "motion_assist")
    assert len(layer.actions) > 0
