"""Tests for the native Python plugin system (manifest, loader, PluginContext)."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# QApplication is required for QObject/Signal — create once before Qt imports.
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from PySide6.QtCore import QObject, Signal  # noqa: E402

from wombat.app.editor import EditorController  # noqa: E402
from wombat.app.project import Project  # noqa: E402
from wombat.app.undo import UndoStack  # noqa: E402
from wombat.domain.action import Action, ActionList  # noqa: E402
from wombat.domain.channel import BlendMode, Channel, Layer  # noqa: E402
from wombat.plugins.api import PluginContext  # noqa: E402
from wombat.plugins.loader import PluginManager, PluginState  # noqa: E402
from wombat.plugins.manifest import (  # noqa: E402
    ManifestError,
    PluginManifest,
    discover,
    discover_with_errors,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PLUGINS = REPO_ROOT / "examples" / "plugins"


# ------------------------------------------------------------------ fixtures

class FakePlayer(QObject):
    """Minimal player stand-in: the attributes/signals PluginContext touches."""

    position_changed = Signal(float)

    def __init__(self, fps: float = 30.0) -> None:
        super().__init__()
        self.frame_time = 1.0 / fps if fps > 0 else 0.0
        self.logical_time = 0.0
        self.duration = 100.0
        self.fps = fps
        self.is_paused = True
        self.mpv = type("M", (), {"path": "/tmp/clip.mp4"})()
        self.paused_calls: list[bool] = []

    def toggle_play(self) -> None:
        self.is_paused = not self.is_paused

    def set_paused(self, paused: bool) -> None:
        self.is_paused = paused
        self.paused_calls.append(paused)

    def seek_exact(self, seconds: float) -> None:
        self.logical_time = seconds


def _editor(*pairs):
    al = ActionList(Action(t, p) for t, p in pairs)
    ch = Channel(name="orig", layers=[Layer(actions=al, name="base")])
    project = Project.new()
    project.channels.append(ch)
    player = FakePlayer()
    ed = EditorController(project, player, UndoStack())
    return ed, project, player, ch


def _ctx(*pairs) -> tuple[PluginContext, EditorController, Channel]:
    ed, project, player, ch = _editor(*pairs)
    ctx = PluginContext("test", ed, player)
    return ctx, ed, ch


def _make_plugin(root: Path, pid: str, body: str, *, toml: str | None = None) -> Path:
    d = root / pid
    d.mkdir(parents=True)
    (d / "__init__.py").write_text(textwrap.dedent(body))
    (d / "plugin.toml").write_text(
        toml
        if toml is not None
        else textwrap.dedent(
            f"""
            [plugin]
            name = "{pid}"
            id = "{pid}"
            version = "0.1.0"
            entry = "{pid}:Plugin"
            api = "1"
            """
        )
    )
    return d


@pytest.fixture(autouse=True)
def _clean_sys_modules():
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        sys.modules.pop(name, None)


# ------------------------------------------------------------------ manifest

def test_manifest_parses_valid():
    m = PluginManifest.from_dict(
        {"plugin": {"name": "X", "id": "x_plug", "entry": "x_plug:Plug", "api": "1"}}
    )
    assert m.id == "x_plug"
    assert m.module_name == "x_plug"
    assert m.class_name == "Plug"
    assert m.api == 1
    assert m.api_compatible


def test_manifest_missing_field():
    with pytest.raises(ManifestError):
        PluginManifest.from_dict({"plugin": {"id": "x", "entry": "x:Y"}})  # no name


@pytest.mark.parametrize("bad_id", ["1bad", "Bad", "with-dash", ""])
def test_manifest_rejects_bad_id(bad_id):
    with pytest.raises(ManifestError):
        PluginManifest.from_dict(
            {"plugin": {"name": "n", "id": bad_id, "entry": "x:Y"}}
        )


@pytest.mark.parametrize("bad_entry", ["noColon", "mod:", ":Cls", "mod:Cls:extra"])
def test_manifest_rejects_bad_entry(bad_entry):
    with pytest.raises(ManifestError):
        PluginManifest.from_dict(
            {"plugin": {"name": "n", "id": "x", "entry": bad_entry}}
        )


def test_discover_skips_malformed(tmp_path):
    _make_plugin(tmp_path, "good", "class Plugin: pass\n")
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "plugin.toml").write_text("this is not valid = toml = =")
    found = discover(tmp_path)
    assert [m.id for m in found] == ["good"]
    ok, errors = discover_with_errors(tmp_path)
    assert len(errors) == 1 and errors[0][0].name == "broken"


# ------------------------------------------------------------------ views / context

def test_channel_and_layer_views_readonly():
    ctx, ed, ch = _ctx((1.0, 10), (2.0, 90))
    cv = ctx.active_channel
    assert cv is not None and cv.name == "orig"
    lv = cv.layers[0]
    assert [a.pos for a in lv.actions] == [10, 90]
    assert isinstance(lv.actions, tuple)  # snapshot, not the live list


def test_edit_session_is_one_undo_step():
    ctx, ed, ch = _ctx((1.0, 10), (2.0, 90))
    assert not ed.can_undo
    with ctx.edit("flip") as edit:
        for a in tuple(ch.layers[0].actions):
            edit.set_pos(a.at, 100 - a.pos)
    assert [a.pos for a in ch.layers[0].actions] == [90, 10]
    assert ed.can_undo
    ed.undo()
    assert [a.pos for a in ch.layers[0].actions] == [10, 90]


def test_edit_add_collapses_near_duplicates():
    ctx, ed, ch = _ctx()
    with ctx.edit("add", target=ch.layers[0]) as edit:
        edit.add(1.0, 20)
        edit.add(1.0001, 80)  # within half a frame of 1.0 → collapses
    assert len(ch.layers[0].actions) == 1
    assert ch.layers[0].actions[0].pos == 80


def test_create_layer_stamps_provenance():
    ctx, ed, ch = _ctx((0.0, 0),)
    lv = ctx.create_layer(
        "gen", blend=BlendMode.OVERRIDE,
        actions=[Action(1.0, 50)], params={"k": 3},
    )
    assert lv is not None
    assert len(ch.layers) == 2
    created = ch.layers[-1]
    assert created.plugin_id == "test"
    assert created.plugin_params == {"k": 3}
    assert [a.pos for a in created.actions] == [50]


def test_flatten_layer_bakes_into_base():
    ctx, ed, ch = _ctx((0.0, 0), (10.0, 0))
    # Plugin layer fully overrides across the timeline.
    ctx.create_layer("gen", blend=BlendMode.OVERRIDE, actions=[Action(0.0, 80), Action(10.0, 80)])
    assert len(ch.layers) == 2
    ctx.flatten_layer(ctx.active_channel.layers[-1])
    assert len(ch.layers) == 1
    assert all(a.pos == 80 for a in ch.layers[0].actions)


def test_player_view():
    ctx, ed, ch = _ctx()
    ctx.player._player.logical_time = 4.0
    assert ctx.player.position == 4.0
    assert ctx.player.duration == 100.0
    assert ctx.player.video_path == "/tmp/clip.mp4"
    ctx.player.play(True)
    assert ctx.player.is_playing
    ctx.player.seek(7.5)
    assert ctx.player.position == 7.5


def test_signal_hook_fires_and_tears_down():
    ctx, ed, ch = _ctx((1.0, 10),)
    calls = []
    ctx.on_actions_changed(lambda: calls.append(1))
    with ctx.edit("x") as edit:
        edit.set_pos(1.0, 50)
    assert len(calls) == 1
    ctx._teardown()
    with ctx.edit("y") as edit:
        edit.set_pos(1.0, 60)
    assert len(calls) == 1  # no further calls after teardown


def test_playhead_hook():
    ctx, ed, ch = _ctx()
    seen = []
    ctx.on_playhead_moved(seen.append)
    ctx.player._player.position_changed.emit(3.0)
    assert seen == [3.0]


# ------------------------------------------------------------------ loader

def _manager(root: Path):
    ed, project, player, ch = _editor((1.0, 10), (2.0, 90))
    contexts: dict[str, PluginContext] = {}

    def factory(manifest):
        ctx = PluginContext(manifest.id, ed, player)
        contexts[manifest.id] = ctx
        return ctx

    return PluginManager(root, factory), ed, ch, contexts


def test_enable_runs_example_invert_plugin():
    mgr, ed, ch, _ = _manager(EXAMPLE_PLUGINS)
    mgr.discover()
    lp = mgr.enable("invert_layer")
    assert lp is not None and lp.state == PluginState.ENABLED
    lp.instance.invert_active()
    assert [a.pos for a in ch.layers[0].actions] == [90, 10]
    assert ed.can_undo


def test_enable_bad_import_is_isolated(tmp_path):
    _make_plugin(tmp_path, "boom", "raise RuntimeError('kaboom')\n")
    mgr, *_ = _manager(tmp_path)
    mgr.discover()
    lp = mgr.enable("boom")
    assert lp.state == PluginState.ERRORED
    assert "import failed" in lp.error


def test_enable_on_load_error_is_isolated(tmp_path):
    _make_plugin(
        tmp_path,
        "failload",
        """
        from wombat.plugins import WombatPlugin

        class Plugin(WombatPlugin):
            def on_load(self, ctx):
                raise ValueError("nope")
        """,
    )
    mgr, *_ = _manager(tmp_path)
    mgr.discover()
    lp = mgr.enable("failload")
    assert lp.state == PluginState.ERRORED
    assert "on_load failed" in lp.error


def test_enable_non_plugin_class_is_isolated(tmp_path):
    _make_plugin(tmp_path, "notplug", "class Plugin:\n    pass\n")
    mgr, *_ = _manager(tmp_path)
    mgr.discover()
    lp = mgr.enable("notplug")
    assert lp.state == PluginState.ERRORED
    assert "not a WombatPlugin" in lp.error


def test_enable_api_mismatch_refused(tmp_path):
    _make_plugin(
        tmp_path,
        "future",
        "from wombat.plugins import WombatPlugin\nclass Plugin(WombatPlugin): pass\n",
        toml=textwrap.dedent(
            """
            [plugin]
            name = "future"
            id = "future"
            entry = "future:Plugin"
            api = "999"
            """
        ),
    )
    mgr, *_ = _manager(tmp_path)
    mgr.discover()
    lp = mgr.enable("future")
    assert lp.state == PluginState.ERRORED
    assert "plugin API" in lp.error


def test_disable_tears_down_hooks(tmp_path):
    _make_plugin(
        tmp_path,
        "hooker",
        """
        from wombat.plugins import WombatPlugin

        class Plugin(WombatPlugin):
            def on_load(self, ctx):
                self.calls = []
                ctx.on_actions_changed(lambda: self.calls.append(1))
        """,
    )
    mgr, ed, ch, _ = _manager(tmp_path)
    mgr.discover()
    lp = mgr.enable("hooker")
    ed.add_action(5.0, 40)
    assert len(lp.instance.calls) == 1
    instance = lp.instance
    mgr.disable("hooker")
    assert lp.state == PluginState.DISABLED
    ed.add_action(6.0, 40)
    assert len(instance.calls) == 1  # hook disconnected on disable
