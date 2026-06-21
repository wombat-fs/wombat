"""The stable public surface handed to plugin authors.

`PluginContext` is the single curated facade into the running app. It deliberately
does NOT expose `EditorController` directly — that's an internal object whose
signature may change. Everything that mutates the document goes through here so
undo, synthesis-cache invalidation, and repaint signals stay correct.

See docs/phase-9-plugin-api.md.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from PySide6.QtCore import SignalInstance

from wombat.domain.action import Action, ActionList
from wombat.domain.channel import BlendMode, Channel, Layer
from wombat.plugins.registry import CommandRegistry, PluginCommand
from wombat.plugins.tasks import TaskHandle, TaskReport, TaskRunner

if TYPE_CHECKING:
    from wombat.app.editor import EditorController
    from wombat.playback.player import VideoPlayer

__all__ = [
    "Action",
    "BlendMode",
    "ChannelView",
    "EditSession",
    "LayerView",
    "PlayerView",
    "PluginContext",
    "PluginLog",
    "TaskHandle",
    "TaskReport",
    "WombatPlugin",
]


# ----------------------------------------------------------------------- views

class LayerView:
    """Read-only view of a Layer. Edits go through ``PluginContext.edit``."""

    __slots__ = ("_layer",)

    def __init__(self, layer: Layer) -> None:
        self._layer = layer

    @property
    def name(self) -> str:
        return self._layer.name

    @property
    def enabled(self) -> bool:
        return self._layer.enabled

    @property
    def blend(self) -> BlendMode:
        return self._layer.blend

    @property
    def span(self) -> tuple[float, float] | None:
        return self._layer.span

    @property
    def plugin_id(self) -> str | None:
        return self._layer.plugin_id

    @property
    def plugin_params(self) -> dict:
        return dict(self._layer.plugin_params)

    @property
    def actions(self) -> tuple[Action, ...]:
        """Immutable snapshot of this layer's actions, sorted by time."""
        return tuple(self._layer.actions)

    def __len__(self) -> int:
        return len(self._layer.actions)

    def __repr__(self) -> str:
        return f"LayerView(name={self._layer.name!r}, n={len(self._layer.actions)})"


class ChannelView:
    """Read-only view of a Channel and its layer stack."""

    __slots__ = ("_channel",)

    def __init__(self, channel: Channel) -> None:
        self._channel = channel

    @property
    def name(self) -> str:
        return self._channel.name

    @property
    def enabled(self) -> bool:
        return self._channel.enabled

    @property
    def layers(self) -> list[LayerView]:
        return [LayerView(layer) for layer in self._channel.layers]

    def synthesized(self) -> tuple[Action, ...]:
        """The flattened, composited action list — what plays and exports."""
        return tuple(self._channel.synthesize())

    def __repr__(self) -> str:
        return f"ChannelView(name={self._channel.name!r}, layers={len(self._channel.layers)})"


class PlayerView:
    """Read + control surface for the video player. No frame pixel access in v1."""

    __slots__ = ("_player",)

    def __init__(self, player: VideoPlayer) -> None:
        self._player = player

    @property
    def position(self) -> float:
        """Current position in seconds (logical — the last requested seek)."""
        return float(self._player.logical_time)

    @property
    def duration(self) -> float:
        return float(self._player.duration)

    @property
    def fps(self) -> float:
        return float(self._player.fps)

    @property
    def is_playing(self) -> bool:
        return not bool(self._player.is_paused)

    @property
    def video_path(self) -> str | None:
        # VideoPlayer has no dedicated property; read mpv's current path defensively.
        mpv = getattr(self._player, "mpv", None)
        path = getattr(mpv, "path", None) if mpv is not None else None
        return path or None

    def play(self, play: bool | None = None) -> None:
        """Toggle play/pause (no arg), or set explicitly."""
        if play is None:
            self._player.toggle_play()
        else:
            self._player.set_paused(not play)

    def seek(self, seconds: float) -> None:
        """Seek to an absolute time (exact)."""
        self._player.seek_exact(float(seconds))


# --------------------------------------------------------------------- logging

class PluginLog:
    """Namespaced logger for a plugin → surfaces in the host's Plugin Log."""

    __slots__ = ("_log",)

    def __init__(self, plugin_id: str) -> None:
        self._log = logging.getLogger(f"wombat.plugin.{plugin_id}")

    def info(self, msg: object, *args: object) -> None:
        self._log.info(msg, *args)

    def warning(self, msg: object, *args: object) -> None:
        self._log.warning(msg, *args)

    def error(self, msg: object, *args: object) -> None:
        self._log.error(msg, *args)

    def debug(self, msg: object, *args: object) -> None:
        self._log.debug(msg, *args)


# ---------------------------------------------------------------- edit session

class EditSession:
    """Batched edit of one layer as a single undo step.

    Obtained from ``PluginContext.edit(...)`` and used as a context manager:

        with ctx.edit("Smooth", target=layer) as edit:
            edit.clear()
            for a in generated:
                edit.add(a.at, a.pos)

    On enter, one undo snapshot is taken. On exit (no exception), the channel's
    synthesis cache is invalidated and one repaint signal fires. Generated content
    is NOT auto-snapped to frames (it is assumed already precise); near-duplicate
    actions within half a frame are collapsed to keep the list well-formed.
    """

    def __init__(self, controller: EditorController, layer: Layer, label: str) -> None:
        self._controller = controller
        self._layer = layer
        self._label = label
        self._active = False

    def __enter__(self) -> EditSession:
        self._active = self._controller.plugin_edit_begin(self._layer, self._label)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Always close the session so the cache/signal stay consistent, even if the
        # plugin raised — the snapshot is already on the undo stack either way.
        # Returning None never suppresses the exception.
        if self._active:
            self._controller.plugin_edit_end(self._layer)
            self._active = False

    @property
    def _gap(self) -> float:
        return self._controller.min_action_gap

    def add(self, at: float, pos: int) -> None:
        """Add an action (seconds, 0–100). Replaces any action at the same time;
        collapses near-duplicates within half a frame."""
        at = max(0.0, float(at))
        al = self._layer.actions
        gap = self._gap
        lo, hi = al.index_range(at - gap, at + gap)
        doomed = [al[i].at for i in range(lo, hi) if al[i].at != at]
        for t in doomed:
            al.remove_at(t)
        al.add(Action(at, int(pos)))

    def remove(self, at: float) -> None:
        """Remove the action at exactly ``at``. No-op if absent."""
        try:
            self._layer.actions.remove_at(float(at))
        except ValueError:
            pass

    def set_pos(self, at: float, pos: int) -> None:
        """Set the position of the action at ``at``. No-op if absent."""
        al = self._layer.actions
        at = float(at)
        lo, hi = al.index_range(at, at)
        if lo < hi:
            al.add(Action(at, int(pos)))

    def set_actions(self, actions: Iterable[Action]) -> None:
        """Replace all actions on this layer with the given ones."""
        self._layer.actions = ActionList(actions)

    def clear(self) -> None:
        """Remove every action on this layer."""
        self._layer.actions = ActionList()


# ------------------------------------------------------------------- context

def _resolve_layer(target: LayerView | Layer | None, fallback: Layer | None) -> Layer | None:
    if target is None:
        return fallback
    if isinstance(target, LayerView):
        return target._layer
    return target


class PluginContext:
    """The curated handle into the running app, passed to ``WombatPlugin.on_load``.

    A plugin keeps this for its lifetime. The host tears down any signal hooks the
    plugin registered when the plugin is unloaded, so a buggy plugin can't leak
    listeners.
    """

    def __init__(
        self,
        plugin_id: str,
        editor: EditorController,
        player: VideoPlayer,
        *,
        storage: dict | None = None,
        commands: CommandRegistry | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self._editor = editor
        self.player = PlayerView(player)
        self.log = PluginLog(plugin_id)
        self.storage: dict = storage if storage is not None else {}
        # (signal, slot) pairs to disconnect on teardown
        self._connections: list[tuple[SignalInstance, Callable]] = []
        # Background tasks owned by this plugin; cancelled on teardown.
        self._tasks = TaskRunner()
        # Commands this plugin contributes; removed from the host registry on teardown.
        # Defaults to a private registry so the context works headless / in tests.
        self._commands = commands if commands is not None else CommandRegistry()

    # ------------------------------------------------------------- read access

    @property
    def channels(self) -> list[ChannelView]:
        # Read the live project via the editor so plugins survive a project swap.
        return [ChannelView(ch) for ch in self._editor.project.channels]

    @property
    def active_channel(self) -> ChannelView | None:
        if not self._editor.has_active_channel:
            return None
        return ChannelView(self._editor.active_channel)

    @property
    def active_layer(self) -> LayerView | None:
        layer = self._editor.active_layer
        return LayerView(layer) if layer is not None else None

    @property
    def selection(self) -> frozenset[float]:
        """Selected action timestamps on the active layer."""
        return self._editor.selection

    def closest_action(self, layer: LayerView | Layer, t: float) -> Action | None:
        al = _resolve_layer(layer, None)
        return al.actions.closest(t) if al is not None else None

    def closest_action_before(self, layer: LayerView | Layer, t: float) -> Action | None:
        al = _resolve_layer(layer, None)
        return al.actions.before(t) if al is not None else None

    def closest_action_after(self, layer: LayerView | Layer, t: float) -> Action | None:
        al = _resolve_layer(layer, None)
        return al.actions.next_after(t) if al is not None else None

    # --------------------------------------------------------------- mutations

    def edit(self, label: str, *, target: LayerView | Layer | None = None) -> EditSession:
        """Open a one-undo-step edit session on ``target`` (default: active layer)."""
        layer = _resolve_layer(target, self._editor.active_layer)
        if layer is None:
            raise RuntimeError("no layer to edit (no active channel/layer)")
        return EditSession(self._editor, layer, label)

    def create_layer(
        self,
        name: str = "plugin",
        *,
        blend: BlendMode = BlendMode.OVERRIDE,
        span: tuple[float, float] | None = None,
        actions: Iterable[Action] | None = None,
        params: dict | None = None,
    ) -> LayerView | None:
        """Create a new top-of-stack layer on the active channel and return a view.

        The layer is stamped with this plugin's id and the given ``params`` so it
        can be reopened and regenerated. One undo step.
        """
        al = ActionList(actions) if actions is not None else None
        layer = self._editor.create_layer(
            name=name,
            blend=blend,
            span=span,
            actions=al,
            plugin_id=self.plugin_id,
            plugin_params=params,
        )
        return LayerView(layer) if layer is not None else None

    def flatten_layer(self, target: LayerView | Layer) -> None:
        """Bake ``target`` and everything beneath it into the base layer (one undo step)."""
        layer = _resolve_layer(target, None)
        if layer is not None:
            self._editor.flatten_layer(layer)

    # ------------------------------------------------------------ async tasks

    def run_async(
        self,
        fn: Callable[[TaskReport], object],
        *,
        on_done: Callable[[object], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        label: str = "",
    ) -> TaskHandle:
        """Run ``fn`` on a worker thread; deliver the result on the GUI thread.

        ``fn(report)`` runs off the GUI thread and MUST NOT touch the model or any
        widget. ``on_done(result)`` / ``on_error(exc)`` / ``on_progress(frac, msg)``
        are invoked on the GUI thread, so they MAY call ``ctx.edit`` and update UI.
        Returns a :class:`TaskHandle` with ``.cancel()``; a cancelled task's
        ``on_done`` is suppressed. All tasks are cancelled when the plugin unloads.
        """
        return self._tasks.run_async(
            fn,
            on_done=on_done,
            on_error=on_error,
            on_progress=on_progress,
            label=label,
        )

    # -------------------------------------------------------------- commands

    def register_command(
        self,
        local_id: str,
        title: str,
        handler: Callable[[], None],
        *,
        default_key: str | None = None,
    ) -> str:
        """Contribute a command that appears under the host's Plugins menu.

        ``local_id`` is namespaced to ``<plugin_id>.<local_id>``. ``default_key`` is
        a Qt key sequence (e.g. ``"Ctrl+Shift+M"``) the user can rebind. The handler
        runs on the GUI thread; for long work call ``run_async`` inside it. Returns
        the namespaced command id.
        """
        cmd = PluginCommand(
            plugin_id=self.plugin_id,
            local_id=local_id,
            title=title,
            handler=handler,
            default_key=default_key,
        )
        self._commands.add(cmd)
        return cmd.id

    # ----------------------------------------------------------- signal hooks

    def on_actions_changed(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` whenever any layer's actions change."""
        self._connect(self._editor.actions_changed, callback)

    def on_layers_changed(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` whenever the layer structure changes (add/remove/reorder/props)."""
        self._connect(self._editor.layer_structure_changed, callback)

    def on_selection_changed(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` whenever the selection (or active channel/layer) changes."""
        self._connect(self._editor.selection_changed, callback)

    def on_playhead_moved(self, callback: Callable[[float], None]) -> None:
        """Call ``callback(seconds)`` as playback position changes."""
        self._connect(self.player._player.position_changed, callback)

    def _connect(self, signal: SignalInstance, callback: Callable) -> None:
        signal.connect(callback)
        self._connections.append((signal, callback))

    def _teardown(self) -> None:
        """Disconnect hooks, cancel background work, drop commands. Called on unload."""
        self._tasks.cancel_all()
        self._commands.remove_plugin(self.plugin_id)
        for signal, callback in self._connections:
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                pass
        self._connections.clear()


# --------------------------------------------------------------------- plugin

class WombatPlugin:
    """Base class for Wombat plugins. Subclass and override the lifecycle hooks.

    A plugin's manifest `entry` points at the subclass. The host instantiates it
    with no arguments, then calls ``on_load(ctx)`` when the plugin is enabled and
    ``on_unload()`` when it is disabled or the app closes.

    Long-running work must not block the GUI thread; use ``ctx.run_async(...)``
    rather than raw threads, and never touch the model or UI from a worker thread.
    """

    def on_load(self, ctx: PluginContext) -> None:
        """Called once when the plugin is enabled. Register hooks, allocate resources."""

    def on_unload(self) -> None:
        """Called when disabled or the app is closing. Release resources, cancel work."""

    def settings_panel(self) -> object | None:
        """Return a declarative settings UI spec, or None for no panel.

        The declarative panel format is added in a later increment; for now return
        None.
        """
        return None
