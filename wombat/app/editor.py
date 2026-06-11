"""EditorController — the single funnel for all funscript mutations.

All writes go through here: snapshot undo, mutate the active layer,
invalidate the synthesis cache, emit signals so the timeline repaints.

Selection is per-(channel, layer): switching channels or layers preserves
each combination's previous selection independently.
"""
from __future__ import annotations

import copy
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from wombat.app.undo import UndoStack
from wombat.domain.action import Action, ActionList
from wombat.domain.channel import BlendMode, Channel, FadeCurve, Layer

if __debug__:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from wombat.app.project import Project
        from wombat.playback.player import VideoPlayer


class EditorController(QObject):
    actions_changed = Signal()          # a layer's actions mutated → repaint / re-export
    selection_changed = Signal()
    history_changed = Signal()          # can_undo / can_redo may have changed
    layer_structure_changed = Signal()  # layers added/removed/reordered/property changed

    def __init__(
        self,
        project: Project,
        player: VideoPlayer,
        undo: UndoStack,
    ) -> None:
        super().__init__()
        self._project = project
        self._player = player
        self._undo = undo
        self._active_idx: int = 0               # index into project.channels
        self._active_layer_indices: dict[int, int] = {}   # ch_idx → layer_idx
        self._selections: dict[tuple[int, int], frozenset[float]] = {}  # (ch,layer) → sel
        self._clipboard: list[Action] = []
        self._snap_to_frame: bool = False
        # gesture state
        self._pre_move_snapshot: ActionList = ActionList()
        self._pre_move_selection: frozenset[float] = frozenset()

    # ----------------------------------------------------------------- project

    def set_project(self, project: Project) -> None:
        self._project = project
        self._active_idx = 0
        self._active_layer_indices = {}
        self._selections = {}
        self._clipboard = []
        self._pre_move_snapshot = ActionList()
        self._pre_move_selection = frozenset()

    # ----------------------------------------------------------------- active channel

    @property
    def has_active_channel(self) -> bool:
        return 0 <= self._active_idx < len(self._project.channels)

    @property
    def active_channel(self) -> Channel:
        return self._project.channels[self._active_idx]

    def set_active_channel_index(self, index: int) -> None:
        self._active_idx = index
        self.selection_changed.emit()

    # ----------------------------------------------------------------- active layer

    @property
    def active_layer_index(self) -> int:
        idx = self._active_layer_indices.get(self._active_idx, 0)
        if self.has_active_channel:
            idx = max(0, min(idx, len(self.active_channel.layers) - 1))
        return idx

    def set_active_layer_index(self, layer_idx: int) -> None:
        if not self.has_active_channel:
            return
        layer_idx = max(0, min(layer_idx, len(self.active_channel.layers) - 1))
        self._active_layer_indices[self._active_idx] = layer_idx
        self.selection_changed.emit()
        self.layer_structure_changed.emit()

    def _layer(self) -> ActionList:
        return self.active_channel.layers[self.active_layer_index].actions

    def _targets(self) -> list[tuple[Channel, int]]:
        return [(self.active_channel, self.active_layer_index)]

    # ----------------------------------------------------------------- selection

    @property
    def selection(self) -> frozenset[float]:
        key = (self._active_idx, self.active_layer_index)
        return self._selections.get(key, frozenset())

    def _set_selection(self, s: frozenset[float]) -> None:
        self._selections[(self._active_idx, self.active_layer_index)] = s

    # ----------------------------------------------------------------- options

    @property
    def snap_to_frame(self) -> bool:
        return self._snap_to_frame

    @snap_to_frame.setter
    def snap_to_frame(self, value: bool) -> None:
        self._snap_to_frame = value

    def _snap(self, at: float) -> float:
        ft = self._player.frame_time
        return round(at / ft) * ft if ft > 0 else at

    # ----------------------------------------------------------------- single edits

    def add_action(self, at: float, pos: int) -> None:
        if not self.has_active_channel:
            return
        if self._snap_to_frame:
            at = self._snap(at)
        at = max(0.0, at)
        self._undo.snapshot("Add action", self._targets(), self.selection)
        self._layer().add(Action(at, pos))
        self.active_channel._invalidate_cache()
        self._emit_actions()

    def remove_action(self, at: float) -> None:
        if not self.has_active_channel:
            return
        self._undo.snapshot("Remove action", self._targets(), self.selection)
        try:
            self._layer().remove_at(at)
        except ValueError:
            return
        self._set_selection(self.selection - {at})
        self.active_channel._invalidate_cache()
        self._emit_actions()
        self.selection_changed.emit()

    def remove_selection(self) -> None:
        """Delete all selected actions in one undo step, then select the nearest survivor."""
        if not self.has_active_channel or not self.selection:
            return
        ref_t = sum(self.selection) / len(self.selection)
        self._undo.snapshot("Delete selection", self._targets(), self.selection)
        layer = self._layer()
        for at in list(self.selection):
            try:
                layer.remove_at(at)
            except ValueError:
                pass
        # Select the action nearest to where the deleted ones were.
        nearest: float | None = None
        if layer.actions:
            nearest = min((a.at for a in layer.actions), key=lambda t: abs(t - ref_t))
        self._set_selection(frozenset({nearest}) if nearest is not None else frozenset())
        self.active_channel._invalidate_cache()
        self._emit_actions()
        self.selection_changed.emit()

    def edit_action(self, old_at: float, new_at: float, new_pos: int) -> None:
        if not self.has_active_channel:
            return
        if self._snap_to_frame:
            new_at = self._snap(new_at)
        self._undo.snapshot("Edit action", self._targets(), self.selection)
        layer = self._layer()
        try:
            layer.remove_at(old_at)
        except ValueError:
            pass
        layer.add(Action(new_at, new_pos))
        if old_at in self.selection:
            self._set_selection((self.selection - {old_at}) | {new_at})
        self.active_channel._invalidate_cache()
        self._emit_actions()

    # ----------------------------------------------------------------- gesture (drag-move)

    def begin_move(self) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        li = self.active_layer_index
        self._undo.begin("Move actions", [(ch, li)], self.selection)
        self._pre_move_snapshot = ch.layers[li].actions.copy()
        self._pre_move_selection = frozenset(self.selection)

    def move_selection(self, d_seconds: float, d_pos: int) -> None:
        """Apply total delta from drag-start; call repeatedly during drag."""
        if not self.has_active_channel or not self._pre_move_selection:
            return
        ch = self.active_channel
        li = self.active_layer_index
        new_al = ActionList()
        new_sel: set[float] = set()
        for a in self._pre_move_snapshot:
            if a.at in self._pre_move_selection:
                new_at = max(0.0, a.at + d_seconds)
                if self._snap_to_frame:
                    new_at = self._snap(new_at)
                new_pos = max(0, min(100, a.pos + d_pos))
                new_al.add(Action(new_at, new_pos))
                new_sel.add(new_at)
            else:
                new_al.add(a)
        ch.layers[li].actions = new_al
        ch._invalidate_cache()
        self._set_selection(frozenset(new_sel))
        self.actions_changed.emit()
        self.selection_changed.emit()

    def end_move(self) -> None:
        self._undo.commit()
        self._pre_move_snapshot = ActionList()
        self._pre_move_selection = frozenset()
        self.history_changed.emit()

    def cancel_move(self) -> None:
        self._undo.cancel()
        self._set_selection(self._pre_move_selection)
        self._pre_move_snapshot = ActionList()
        self._pre_move_selection = frozenset()
        self.actions_changed.emit()
        self.selection_changed.emit()
        self.history_changed.emit()

    # ----------------------------------------------------------------- selection ops

    def select(self, at: float, additive: bool = False) -> None:
        if additive:
            self._set_selection(self.selection | {at})
        else:
            self._set_selection(frozenset({at}))
        self.selection_changed.emit()

    def select_time_range(self, t0: float, t1: float, additive: bool = False) -> None:
        if not self.has_active_channel:
            return
        lo, hi = self._layer().index_range(t0, t1)
        ats = frozenset(self._layer()[i].at for i in range(lo, hi))
        self._set_selection((self.selection | ats) if additive else ats)
        self.selection_changed.emit()

    def select_all(self) -> None:
        if not self.has_active_channel:
            return
        self._set_selection(frozenset(a.at for a in self._layer()))
        self.selection_changed.emit()

    def clear_selection(self) -> None:
        self._set_selection(frozenset())
        self.selection_changed.emit()

    def invert_selection(self) -> None:
        if not self.has_active_channel:
            return
        all_ats = frozenset(a.at for a in self._layer())
        self._set_selection(all_ats - self.selection)
        self.selection_changed.emit()

    def select_top(self) -> None:
        from wombat.domain.transforms import top_points
        self._select_by_transform(top_points)

    def select_mid(self) -> None:
        from wombat.domain.transforms import mid_points
        self._select_by_transform(mid_points)

    def select_bottom(self) -> None:
        from wombat.domain.transforms import bottom_points
        self._select_by_transform(bottom_points)

    def _select_by_transform(self, fn: Callable[[ActionList], ActionList]) -> None:
        if not self.has_active_channel:
            return
        result = fn(self._layer())
        self._set_selection(frozenset(a.at for a in result))
        self.selection_changed.emit()

    # ----------------------------------------------------------------- transforms

    def equalize_selection(self) -> None:
        from wombat.domain.transforms import equalize
        self._transform("Equalize", equalize)

    def invert_positions(self) -> None:
        from wombat.domain.transforms import invert
        self._transform("Invert", invert)

    def simplify_selection(self, epsilon: float) -> None:
        from wombat.domain.transforms import simplify_rdp
        self._transform("Simplify", lambda al: simplify_rdp(al, epsilon))

    def _transform(
        self, desc: str, fn: Callable[[ActionList], ActionList]
    ) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        li = self.active_layer_index
        layer_al = ch.layers[li].actions
        if not layer_al:
            return
        self._undo.snapshot(desc, [(ch, li)], self.selection)
        if self.selection:
            sel_list = ActionList(a for a in layer_al if a.at in self.selection)
            transformed = fn(sel_list)
            new_al = ActionList(a for a in layer_al if a.at not in self.selection)
            for a in transformed:
                new_al.add(a)
            new_sel = frozenset(a.at for a in transformed)
        else:
            new_al = fn(layer_al)
            new_sel = frozenset()
        ch.layers[li].actions = new_al
        ch._invalidate_cache()
        self._set_selection(new_sel)
        self._emit_actions()
        self.selection_changed.emit()

    # ----------------------------------------------------------------- clipboard

    def copy(self) -> None:
        if not self.has_active_channel or not self.selection:
            return
        self._clipboard = sorted(
            (a for a in self._layer() if a.at in self.selection),
            key=lambda a: a.at,
        )

    def cut(self) -> None:
        self.copy()
        self.remove_selection()

    def paste(self, at_playhead: float) -> None:
        if not self.has_active_channel or not self._clipboard:
            return
        ch = self.active_channel
        li = self.active_layer_index
        self._undo.snapshot("Paste", [(ch, li)], self.selection)
        t0 = self._clipboard[0].at
        new_ats: set[float] = set()
        for a in self._clipboard:
            at = at_playhead + (a.at - t0)
            if self._snap_to_frame:
                at = self._snap(at)
            ch.layers[li].actions.add(Action(at, a.pos))
            new_ats.add(at)
        ch._invalidate_cache()
        self._set_selection(frozenset(new_ats))
        self._emit_actions()
        self.selection_changed.emit()

    def paste_exact(self) -> None:
        if not self.has_active_channel or not self._clipboard:
            return
        ch = self.active_channel
        li = self.active_layer_index
        self._undo.snapshot("Paste exact", [(ch, li)], self.selection)
        new_ats: set[float] = set()
        for a in self._clipboard:
            ch.layers[li].actions.add(a)
            new_ats.add(a.at)
        ch._invalidate_cache()
        self._set_selection(frozenset(new_ats))
        self._emit_actions()
        self.selection_changed.emit()

    # ----------------------------------------------------------------- layer structural ops

    def add_layer(
        self,
        name: str = "layer",
        *,
        blend: BlendMode = BlendMode.OVERRIDE,
        span: tuple[float, float] | None = None,
    ) -> None:
        """Add a new empty layer above the current active layer."""
        if not self.has_active_channel:
            return
        ch = self.active_channel
        self._undo.snapshot_structural("Add layer", ch, self.active_layer_index, self.selection)
        new_layer = Layer(actions=ActionList(), name=name, blend=blend, span=span)
        insert_at = self.active_layer_index
        ch.layers.insert(insert_at, new_layer)
        self._active_layer_indices[self._active_idx] = insert_at
        ch._invalidate_cache()
        self._emit_structure()

    def duplicate_layer(self, index: int | None = None) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        li = self.active_layer_index if index is None else index
        if not (0 <= li < len(ch.layers)):
            return
        self._undo.snapshot_structural("Duplicate layer", ch, self.active_layer_index, self.selection)
        dup = copy.deepcopy(ch.layers[li])
        dup.name = dup.name + " copy"
        ch.layers.insert(li + 1, dup)
        self._active_layer_indices[self._active_idx] = li + 1
        ch._invalidate_cache()
        self._emit_structure()

    def remove_layer(self, index: int | None = None) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        li = self.active_layer_index if index is None else index
        if not (0 <= li < len(ch.layers)):
            return
        if len(ch.layers) == 1:
            return  # always keep at least one layer
        self._undo.snapshot_structural("Remove layer", ch, self.active_layer_index, self.selection)
        del ch.layers[li]
        new_li = max(0, min(li, len(ch.layers) - 1))
        self._active_layer_indices[self._active_idx] = new_li
        ch._invalidate_cache()
        self._emit_structure()

    def reorder_layer(self, src: int, dst: int) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        n = len(ch.layers)
        if not (0 <= src < n and 0 <= dst < n and src != dst):
            return
        self._undo.snapshot_structural("Reorder layer", ch, self.active_layer_index, self.selection)
        layer = ch.layers.pop(src)
        ch.layers.insert(dst, layer)
        if self.active_layer_index == src:
            self._active_layer_indices[self._active_idx] = dst
        ch._invalidate_cache()
        self._emit_structure()

    def set_blend(self, index: int, blend: BlendMode) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= index < len(ch.layers)):
            return
        self._undo.snapshot_structural("Set blend", ch, self.active_layer_index, self.selection)
        ch.layers[index].blend = blend
        ch._invalidate_cache()
        self._emit_structure()

    def set_center(self, index: int, center: int) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= index < len(ch.layers)):
            return
        self._undo.snapshot_structural("Set center", ch, self.active_layer_index, self.selection)
        ch.layers[index].center = max(0, min(100, center))
        ch._invalidate_cache()
        self._emit_structure()

    def set_span(self, index: int, span: tuple[float, float] | None) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= index < len(ch.layers)):
            return
        self._undo.snapshot_structural("Set span", ch, self.active_layer_index, self.selection)
        ch.layers[index].span = span
        ch._invalidate_cache()
        self._emit_structure()

    def set_fades(self, index: int, fade_in: float, fade_out: float) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= index < len(ch.layers)):
            return
        self._undo.snapshot_structural("Set fades", ch, self.active_layer_index, self.selection)
        ch.layers[index].fade_in = max(0.0, fade_in)
        ch.layers[index].fade_out = max(0.0, fade_out)
        ch._invalidate_cache()
        self._emit_structure()

    def set_fade_curve(self, index: int, curve: FadeCurve) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= index < len(ch.layers)):
            return
        self._undo.snapshot_structural("Set fade curve", ch, self.active_layer_index, self.selection)
        ch.layers[index].fade_curve = curve
        ch._invalidate_cache()
        self._emit_structure()

    def set_layer_enabled(self, index: int, enabled: bool) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= index < len(ch.layers)):
            return
        self._undo.snapshot_structural("Toggle layer", ch, self.active_layer_index, self.selection)
        ch.layers[index].enabled = enabled
        ch._invalidate_cache()
        self._emit_structure()

    # ----------------------------------------------------------------- span/fade live drag gestures

    def begin_span_drag(self, layer_idx: int) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        self._undo.begin_structural("Set span", ch, self.active_layer_index, self.selection)

    def update_span_live(self, layer_idx: int, span: tuple[float, float] | None) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if 0 <= layer_idx < len(ch.layers):
            ch.layers[layer_idx].span = span
            ch._invalidate_cache()
            self._emit_structure()

    def end_span_drag(self) -> None:
        self._undo.commit()
        self.history_changed.emit()

    def begin_fade_drag(self, layer_idx: int) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        self._undo.begin_structural("Set fades", ch, self.active_layer_index, self.selection)

    def update_fades_live(self, layer_idx: int, fade_in: float, fade_out: float) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if 0 <= layer_idx < len(ch.layers):
            ch.layers[layer_idx].fade_in = max(0.0, fade_in)
            ch.layers[layer_idx].fade_out = max(0.0, fade_out)
            ch._invalidate_cache()
            self._emit_structure()

    def end_fade_drag(self) -> None:
        self._undo.commit()
        self.history_changed.emit()

    def rename_layer(self, index: int, name: str) -> None:
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= index < len(ch.layers)):
            return
        self._undo.snapshot_structural("Rename layer", ch, self.active_layer_index, self.selection)
        ch.layers[index].name = name
        self._emit_structure()

    # ----------------------------------------------------------------- snippets

    def insert_snippet_as_layer(
        self,
        snippet: object,
        span: tuple[float, float],
        *,
        blend: BlendMode = BlendMode.ADDITIVE,
        name: str = "snippet",
        fade_in: float = 0.0,
        fade_out: float = 0.0,
    ) -> None:
        """Generate snippet content and insert it as a new layer. One undo step.

        The base sampler passed to generate() is the current synthesis of the
        active channel — so base-dependent pos algorithms read the right signal.
        """
        if not self.has_active_channel:
            return
        ch = self.active_channel
        base_al = ch.synthesize()
        fps = (1.0 / self._player.frame_time) if self._player.frame_time > 0 else None
        actions = snippet.generate(  # type: ignore[union-attr]
            span,
            base=base_al,
            fps=fps,
            snap_to_frame=self._snap_to_frame,
        )
        self._undo.snapshot_structural(
            "Insert snippet", ch, self.active_layer_index, self.selection
        )
        insert_at = self.active_layer_index
        new_layer = Layer(
            actions=actions,
            name=name,
            blend=blend,
            span=span,
            fade_in=fade_in,
            fade_out=fade_out,
            snippet=snippet,
            snippet_entry_name=name,
        )
        ch.layers.insert(insert_at, new_layer)
        self._active_layer_indices[self._active_idx] = insert_at
        ch._invalidate_cache()
        self._emit_structure()

    def update_snippet_layer(
        self,
        layer_index: int,
        snippet: object,
        span: tuple[float, float],
        *,
        blend: "BlendMode",
        fade_in: float,
        fade_out: float,
    ) -> None:
        """Regenerate a live snippet layer with updated parameters. One undo step."""
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= layer_index < len(ch.layers)):
            return
        base_al = ch.synthesize()
        fps = (1.0 / self._player.frame_time) if self._player.frame_time > 0 else None
        actions = snippet.generate(  # type: ignore[union-attr]
            span,
            base=base_al,
            fps=fps,
            snap_to_frame=self._snap_to_frame,
        )
        self._undo.snapshot_structural("Update snippet layer", ch, self.active_layer_index, self.selection)
        layer = ch.layers[layer_index]
        layer.actions = actions
        layer.span = span
        layer.blend = blend
        layer.fade_in = fade_in
        layer.fade_out = fade_out
        layer.snippet = snippet
        ch._invalidate_cache()
        self._emit_structure()

    def fill_layer_with_snippet(
        self,
        layer_index: int,
        snippet: object,
        span: tuple[float, float],
    ) -> None:
        """Replace an existing layer's actions with generated snippet content. One undo step.

        The base sampler is synthesized from layers below `layer_index`.
        """
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (0 <= layer_index < len(ch.layers)):
            return
        from wombat.domain.synthesis import synthesize
        layers_below = ch.layers[:layer_index]
        base_al = synthesize(layers_below) if layers_below else None
        fps = (1.0 / self._player.frame_time) if self._player.frame_time > 0 else None
        actions = snippet.generate(  # type: ignore[union-attr]
            span,
            base=base_al,
            fps=fps,
            snap_to_frame=self._snap_to_frame,
        )
        self._undo.snapshot("Fill layer with snippet", [(ch, layer_index)], self.selection)
        ch.layers[layer_index].actions = actions
        ch._invalidate_cache()
        self._emit_actions()

    # ----------------------------------------------------------------- event application

    def apply_event_layers(
        self,
        insertions: list[tuple[str, object]],
        description: str = "Apply event",
    ) -> None:
        """Insert layers into multiple channels as one undo step.

        Args:
            insertions: List of (channel_name, Layer) pairs from translate_event().
                        Layers for unknown channel names are skipped with a warning.
            description: Undo entry description.
        """
        if not insertions:
            return

        # Resolve channel names to Channel objects; warn and skip unknowns
        ch_map = {ch.name: ch for ch in self._project.channels}
        resolved: list[tuple[object, object]] = []  # (Channel, Layer)
        for ch_name, layer in insertions:
            ch = ch_map.get(ch_name)
            if ch is None:
                import warnings
                warnings.warn(
                    f"Event targets channel {ch_name!r} which does not exist — skipped",
                    stacklevel=2,
                )
                continue
            resolved.append((ch, layer))

        if not resolved:
            return

        # Snapshot all affected channels (de-duplicated) in one undo entry
        seen: dict[int, tuple[object, int]] = {}  # id(ch) -> (ch, active_layer_idx)
        for ch, _ in resolved:
            if id(ch) not in seen:
                ch_idx = self._channel_index(ch)  # type: ignore[arg-type]
                ali = self._active_layer_indices.get(ch_idx or 0, 0) if ch_idx is not None else 0
                seen[id(ch)] = (ch, ali)

        self._undo.snapshot_multi_structural(
            description,
            [(ch, ali) for ch, ali in seen.values()],  # type: ignore[misc]
            self.selection,
        )

        # Insert each layer at the top of its channel's layer stack
        for ch, layer in resolved:
            ch.layers.append(layer)  # type: ignore[union-attr]
            ch._invalidate_cache()  # type: ignore[union-attr]

        self._emit_structure()

    # ----------------------------------------------------------------- recording gesture

    def begin_recording(self) -> None:
        """Open a recording gesture: all subsequent ``record_action`` calls form one undo step."""
        if not self.has_active_channel:
            return
        ch = self.active_channel
        li = self.active_layer_index
        self._undo.begin("Record", [(ch, li)], self.selection)

    def record_action(self, at: float, pos: int) -> None:
        """Insert a sampled action without creating a new undo entry (inside a recording gesture)."""
        if not self.has_active_channel:
            return
        at = max(0.0, at)
        self._layer().add(Action(at, pos))
        self.active_channel._invalidate_cache()
        self.actions_changed.emit()

    def end_recording(self) -> None:
        """Commit the recording gesture as a single undo entry."""
        self._undo.commit()
        self.history_changed.emit()

    def cancel_recording(self) -> None:
        """Abandon the recording gesture and restore pre-recording state."""
        self._undo.cancel()
        self.actions_changed.emit()
        self.history_changed.emit()

    # ----------------------------------------------------------------- history

    def undo(self) -> None:
        entry = self._undo.undo(self.selection)
        if entry is not None:
            for snap in entry.snapshots:
                ch_idx = self._channel_index(snap.channel)
                if ch_idx is not None:
                    self._selections[(ch_idx, snap.layer_index)] = snap.selection
            for snap in entry.structural:
                ch_idx = self._channel_index(snap.channel)
                if ch_idx is not None:
                    self._active_layer_indices[ch_idx] = snap.active_layer_index
            self._emit_actions()
            self.selection_changed.emit()
            self.history_changed.emit()
            self.layer_structure_changed.emit()

    def redo(self) -> None:
        entry = self._undo.redo(self.selection)
        if entry is not None:
            for snap in entry.snapshots:
                ch_idx = self._channel_index(snap.channel)
                if ch_idx is not None:
                    self._selections[(ch_idx, snap.layer_index)] = snap.selection
            for snap in entry.structural:
                ch_idx = self._channel_index(snap.channel)
                if ch_idx is not None:
                    self._active_layer_indices[ch_idx] = snap.active_layer_index
            self._emit_actions()
            self.selection_changed.emit()
            self.history_changed.emit()
            self.layer_structure_changed.emit()

    @property
    def can_undo(self) -> bool:
        return self._undo.can_undo

    @property
    def can_redo(self) -> bool:
        return self._undo.can_redo

    # ----------------------------------------------------------------- helpers

    def _channel_index(self, ch: Channel) -> int | None:
        try:
            return self._project.channels.index(ch)
        except ValueError:
            return None

    def _emit_actions(self) -> None:
        self.actions_changed.emit()
        self.history_changed.emit()

    def _emit_structure(self) -> None:
        self.layer_structure_changed.emit()
        self.actions_changed.emit()
        self.history_changed.emit()
