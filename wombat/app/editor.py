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
import logging

from wombat.domain.channel import BlendMode, Channel, FadeCurve, Layer

log = logging.getLogger(__name__)

# Axis names used in funscript-tools YAMLs that differ from Wombat's channel presets.
# Channel presets now match funscript-tools' axis names directly (alpha, beta, volume,
# frequency, pulse_frequency, pulse_width, pulse_rise_time), so only genuine variants
# need aliasing. Looked up before falling back to "no such channel" — first match wins.
_AXIS_ALIASES: dict[str, str] = {
    "volume-prostate": "volume",        # secondary prostate axis; fold into regular volume
    "pulse_rise":      "pulse_rise_time",  # tolerate the short form for the rise-time axis
}

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
        self._selection_start: float | None = None   # mark for set-start/set-end range select
        self._clipboard: list[Action] = []
        self._snap_to_frame: bool = False
        self._snap_to_beats: bool = False
        self._beats = None   # BeatGrid | None — snap target for snap-to-beats
        # gesture state
        self._pre_move_snapshot: ActionList = ActionList()
        self._pre_move_selection: frozenset[float] = frozenset()

    # ----------------------------------------------------------------- project

    @property
    def project(self) -> Project:
        """The current project. Read live so consumers survive a project swap."""
        return self._project

    def set_project(self, project: Project) -> None:
        self._project = project
        self._active_idx = 0
        self._active_layer_indices = {}
        self._selections = {}
        self._selection_start = None
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

    @property
    def active_layer(self) -> "Layer | None":
        if not self.has_active_channel:
            return None
        ch = self.active_channel
        idx = self.active_layer_index
        if 0 <= idx < len(ch.layers):
            return ch.layers[idx]
        return None

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

    @property
    def snap_to_beats(self) -> bool:
        return self._snap_to_beats

    @snap_to_beats.setter
    def snap_to_beats(self, value: bool) -> None:
        self._snap_to_beats = value

    def set_beats(self, grid) -> None:
        """Set the beat grid used when snap-to-beats is enabled (BeatGrid or None)."""
        self._beats = grid

    def _snap(self, at: float) -> float:
        """Apply the active snap modes to a timestamp.

        Beats first (musical intent), then frame-quantize the result, so a
        beat-snapped point still lands on a frame boundary when both are on.
        Returns ``at`` unchanged when no snap mode is active.
        """
        if self._snap_to_beats and self._beats is not None and len(self._beats):
            nb = self._beats.nearest(at)
            if nb is not None:
                at = nb
        if self._snap_to_frame:
            ft = self._player.frame_time
            if ft > 0:
                at = round(at / ft) * ft
        return at

    # ----------------------------------------------------------------- single edits

    def _min_gap(self) -> float:
        """Minimum spacing between two actions: half a video frame, or a small
        floor (~5 ms, below funscript ms resolution) when no video is loaded."""
        ft = self._player.frame_time
        return ft / 2.0 if ft > 0 else 0.005

    def _remove_near(self, layer: ActionList, at: float, gap: float) -> None:
        """Delete any existing actions within `gap` of `at` (an exact match is left
        for add() to overwrite). Prevents virtually-coincident duplicate actions."""
        lo, hi = layer.index_range(at - gap, at + gap)
        doomed = [layer[i].at for i in range(lo, hi) if layer[i].at != at]
        for t in doomed:
            layer.remove_at(t)

    def add_action(self, at: float, pos: int) -> None:
        if not self.has_active_channel:
            return
        at = self._snap(at)
        at = max(0.0, at)
        self._undo.snapshot("Add action", self._targets(), self.selection)
        layer = self._layer()
        self._remove_near(layer, at, self._min_gap())
        layer.add(Action(at, pos))
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
        if layer:
            nearest = min((a.at for a in layer), key=lambda t: abs(t - ref_t))
        self._set_selection(frozenset({nearest}) if nearest is not None else frozenset())
        self.active_channel._invalidate_cache()
        self._emit_actions()
        self.selection_changed.emit()

    def isolate_action(self) -> None:
        """Remove the immediate neighbours of the action closest to the playhead.

        Mirrors OFS's Isolate: keeps the closest action and deletes the points on
        either side of it, so a single peak/valley can be reshaped in isolation.
        """
        if not self.has_active_channel:
            return
        layer = self._layer()
        closest = layer.closest(self._player.logical_time)
        if closest is None:
            return
        prev = layer.before(closest.at)
        nxt = layer.next_after(closest.at)
        if prev is None and nxt is None:
            return
        self._undo.snapshot("Isolate action", self._targets(), self.selection)
        for neighbour in (prev, nxt):
            if neighbour is not None:
                try:
                    layer.remove_at(neighbour.at)
                except ValueError:
                    pass
        self._set_selection(frozenset({closest.at}))
        self.active_channel._invalidate_cache()
        self._emit_actions()
        self.selection_changed.emit()

    def edit_action(self, old_at: float, new_at: float, new_pos: int) -> None:
        if not self.has_active_channel:
            return
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

    def set_selection_pos(self, pos: int) -> bool:
        """Set every selected action's pos to ``pos`` in one undo step.

        Returns True if anything was edited, False if there was nothing to do
        (no active channel or empty selection) so the caller can fall back to
        inserting a new action instead.
        """
        if not self.has_active_channel or not self.selection:
            return False
        pos = max(0, min(100, pos))
        layer = self._layer()
        targets = [a.at for a in layer if a.at in self.selection]
        if not targets:
            return False
        self._undo.snapshot("Set position", self._targets(), self.selection)
        for at in targets:
            layer.remove_at(at)
            layer.add(Action(at, pos))
        self.active_channel._invalidate_cache()
        self._emit_actions()
        self.selection_changed.emit()
        return True

    def nudge_selection(self, d_seconds: float = 0.0, d_pos: int = 0) -> bool:
        """Shift every selected action by a small (time, pos) delta in one undo step.

        Unlike a drag-move this bypasses snap-to-frame on purpose — nudging is
        meant for sub-frame fine-tuning. Returns True if anything moved, False
        if there was nothing to nudge.
        """
        if not self.has_active_channel or not self.selection:
            return False
        ch = self.active_channel
        li = self.active_layer_index
        layer_al = ch.layers[li].actions
        sel = self.selection
        if not any(a.at in sel for a in layer_al):
            return False
        self._undo.snapshot("Nudge", [(ch, li)], sel)
        new_al = ActionList()
        new_sel: set[float] = set()
        for a in layer_al:
            if a.at in sel:
                new_at = max(0.0, a.at + d_seconds)
                new_pos = max(0, min(100, a.pos + d_pos))
                new_al.add(Action(new_at, new_pos))
                new_sel.add(new_at)
            else:
                new_al.add(a)
        ch.layers[li].actions = new_al
        ch._invalidate_cache()
        self._set_selection(frozenset(new_sel))
        self._emit_actions()
        self.selection_changed.emit()
        return True

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
        # Collapse only at commit: mid-drag the layer is rebuilt from the snapshot
        # each frame, so removing a stationary neighbour earlier would destroy it
        # permanently when the dragged action moves on. The dragged (selected)
        # actions win over the stationary ones they land on.
        if self.has_active_channel and self._pre_move_selection:
            self._collapse_near_selection()
        self._undo.commit()
        self._pre_move_snapshot = ActionList()
        self._pre_move_selection = frozenset()
        self.history_changed.emit()

    def _collapse_near_selection(self) -> None:
        """Remove unselected actions sitting within a min-gap of any selected action."""
        ch = self.active_channel
        layer = ch.layers[self.active_layer_index].actions
        sel = self.selection
        gap = self._min_gap()
        doomed: set[float] = set()
        for s_at in sel:
            lo, hi = layer.index_range(s_at - gap, s_at + gap)
            for i in range(lo, hi):
                a = layer[i]
                if a.at not in sel:
                    doomed.add(a.at)
        if not doomed:
            return
        for t in doomed:
            try:
                layer.remove_at(t)
            except ValueError:
                pass
        ch._invalidate_cache()
        self.actions_changed.emit()

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

    # ----------------------------------------------------- playhead-relative select

    def select_left_of_playhead(self, additive: bool = False) -> None:
        """Select every action at or before the playhead."""
        self._select_time_span(0.0, self._player.logical_time, additive)

    def select_right_of_playhead(self, additive: bool = False) -> None:
        """Select every action at or after the playhead."""
        self._select_time_span(self._player.logical_time, self._player.duration, additive)

    def _select_time_span(self, t0: float, t1: float, additive: bool) -> None:
        if not self.has_active_channel:
            return
        ats = frozenset(a.at for a in self._layer() if t0 <= a.at <= t1)
        self._set_selection((self.selection | ats) if additive else ats)
        self.selection_changed.emit()

    def set_selection_start(self) -> None:
        """Mark the playhead as the start of a range; pair with set_selection_end()."""
        self._selection_start = self._player.logical_time

    def set_selection_end(self) -> None:
        """Select all actions between the marked start (set_selection_start) and the playhead."""
        if self._selection_start is None or not self.has_active_channel:
            return
        lo, hi = sorted((self._selection_start, self._player.logical_time))
        ats = frozenset(a.at for a in self._layer() if lo <= a.at <= hi)
        self._set_selection(ats)
        self._selection_start = None
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

    def merge_layer_down(self, index: int) -> None:
        """Merge the layer at ``index`` into the layer below it (``index - 1``).

        The lower layer is replaced by the composite of the two and the upper layer
        is removed — the layer-stack equivalent of "merge down" in image editors.
        The lower layer is treated as the base of the pair, so its blend/span/fades
        (its relationship to the rest of the stack below) are preserved on the
        result. No-op on the base layer (nothing below it). One undo step.
        """
        if not self.has_active_channel:
            return
        ch = self.active_channel
        if not (1 <= index < len(ch.layers)):
            return
        from wombat.domain.synthesis import get_default_params, synthesize
        lower = ch.layers[index - 1]
        upper = ch.layers[index]
        merged_actions = synthesize([lower, upper], get_default_params())
        self._undo.snapshot_structural(
            "Merge layer down", ch, self.active_layer_index, self.selection
        )
        merged = Layer(
            actions=merged_actions,
            name=lower.name,
            enabled=lower.enabled,
            blend=lower.blend,
            span=lower.span,
            fade_in=lower.fade_in,
            fade_out=lower.fade_out,
            center=lower.center,
            fade_curve=lower.fade_curve,
        )
        ch.layers[index - 1] = merged
        del ch.layers[index]
        ci = self._channel_index(ch)
        if ci is not None:
            cur = self._active_layer_indices.get(ci, 0)
            # The merged result lives at index-1; keep focus sensible.
            new_idx = index - 1 if cur >= index else cur
            self._active_layer_indices[ci] = max(0, min(new_idx, len(ch.layers) - 1))
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
        *,
        event_name: str | None = None,
        event_start_ms: float | None = None,
        event_param_overrides: dict | None = None,
    ) -> None:
        """Insert layers into multiple channels as one undo step.

        Args:
            insertions: List of (channel_name, Layer) pairs from translate_event().
                        Layers for unknown channel names are skipped with a warning.
            description: Undo entry description.
        """
        if not insertions:
            return

        # Resolve channel names to Channel objects; warn and skip unknowns.
        # Try exact name first, then consult the alias table for known YAML↔Wombat
        # naming differences (e.g. pulse_width → pulse-width).
        ch_map = {ch.name: ch for ch in self._project.channels}
        resolved: list[tuple[object, object]] = []  # (Channel, Layer)
        seen_ch_ids: set[int] = set()               # de-duplicate alias collisions
        for ch_name, layer in insertions:
            ch = ch_map.get(ch_name) or ch_map.get(_AXIS_ALIASES.get(ch_name, ""))
            if ch is None:
                log.warning("Event targets channel %r which does not exist — skipped", ch_name)
                continue
            if id(ch) in seen_ch_ids:
                continue  # alias mapped two YAML axes to the same channel; insert once
            seen_ch_ids.add(id(ch))
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

        # Stamp event metadata onto each layer for live re-editing
        if event_name is not None:
            import uuid as _uuid
            group_id = str(_uuid.uuid4())
            for _, layer in resolved:
                layer.event_name = event_name  # type: ignore[union-attr]
                layer.event_group_id = group_id  # type: ignore[union-attr]
                layer.event_start_ms = event_start_ms  # type: ignore[union-attr]
                layer.event_param_overrides = dict(event_param_overrides or {})  # type: ignore[union-attr]

        # Insert each layer at the top of its channel's layer stack
        for ch, layer in resolved:
            ch.layers.append(layer)  # type: ignore[union-attr]
            ch._invalidate_cache()  # type: ignore[union-attr]

        self._emit_structure()

    def update_event_layers(
        self,
        group_id: str,
        event: object,
        lib: object,
        start_ms: float,
        param_overrides: dict | None = None,
        event_name: str | None = None,
    ) -> None:
        """Replace all layers from an event group with freshly translated content.

        Finds every layer in every channel whose event_group_id matches, removes
        them, re-translates the event, and re-inserts the new layers — all in one
        undo step.
        """
        from wombat.domain.events.apply import translate_event

        # Collect all channels that contain layers with this group_id
        affected: list[tuple[object, list[int]]] = []  # (Channel, [layer_indices])
        for ch in self._project.channels:
            indices = [
                i for i, lay in enumerate(ch.layers)
                if getattr(lay, "event_group_id", None) == group_id
            ]
            if indices:
                affected.append((ch, indices))

        if not affected:
            return

        # Snapshot all affected channels
        seen: dict[int, tuple[object, int]] = {}
        for ch, _ in affected:
            if id(ch) not in seen:
                ch_idx = self._channel_index(ch)  # type: ignore[arg-type]
                ali = self._active_layer_indices.get(ch_idx or 0, 0) if ch_idx is not None else 0
                seen[id(ch)] = (ch, ali)

        desc = f"Update event: {event_name}" if event_name else "Update event"
        self._undo.snapshot_multi_structural(
            desc,
            [(ch, ali) for ch, ali in seen.values()],  # type: ignore[misc]
            self.selection,
        )

        # Remove old event layers (reverse order to preserve indices)
        for ch, indices in affected:
            for i in sorted(indices, reverse=True):
                del ch.layers[i]  # type: ignore[union-attr]
            ch._invalidate_cache()  # type: ignore[union-attr]

        # Re-translate and insert new layers
        try:
            insertions = translate_event(  # type: ignore[call-overload]
                event, lib, start_ms,
                param_overrides=param_overrides or None,
                group=event_name or "",
            )
        except Exception as exc:
            log.warning("update_event_layers: translate_event failed: %s", exc)
            self._emit_structure()
            return

        import uuid as _uuid
        new_group_id = str(_uuid.uuid4())
        ch_map = {ch.name: ch for ch in self._project.channels}
        seen_ch_ids: set[int] = set()
        for ch_name, layer in insertions:
            ch = ch_map.get(ch_name) or ch_map.get(_AXIS_ALIASES.get(ch_name, ""))
            if ch is None:
                continue
            if id(ch) in seen_ch_ids:
                continue
            seen_ch_ids.add(id(ch))
            layer.event_name = event_name  # type: ignore[union-attr]
            layer.event_group_id = new_group_id  # type: ignore[union-attr]
            layer.event_start_ms = start_ms  # type: ignore[union-attr]
            layer.event_param_overrides = dict(param_overrides or {})  # type: ignore[union-attr]
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

    # ----------------------------------------------------------------- plugin host ops

    def _find_layer(self, layer: Layer) -> tuple[Channel, int] | None:
        """Locate a Layer object in the project by identity → (channel, index)."""
        for ch in self._project.channels:
            for i, lay in enumerate(ch.layers):
                if lay is layer:
                    return ch, i
        return None

    @property
    def min_action_gap(self) -> float:
        """Minimum spacing between two actions (half a frame, or ~5 ms floor).

        Exposed so plugin edits can de-duplicate generated actions the same way
        interactive edits do.
        """
        return self._min_gap()

    def create_layer(
        self,
        *,
        name: str = "plugin",
        channel: Channel | None = None,
        blend: BlendMode = BlendMode.OVERRIDE,
        span: tuple[float, float] | None = None,
        actions: ActionList | None = None,
        plugin_id: str | None = None,
        plugin_params: dict | None = None,
    ) -> Layer | None:
        """Create a new top-of-stack layer for generated content and return it.

        Unlike ``add_layer`` (which inserts an empty layer at the active index for
        interactive use), this appends on top, accepts initial actions, and stamps
        plugin provenance so the layer can later be regenerated. One undo step.
        """
        ch = channel if channel is not None else (self.active_channel if self.has_active_channel else None)
        if ch is None:
            return None
        ch_idx = self._channel_index(ch)
        ali = self._active_layer_indices.get(ch_idx, 0) if ch_idx is not None else 0
        self._undo.snapshot_structural("Create layer", ch, ali, self.selection)
        layer = Layer(
            actions=actions if actions is not None else ActionList(),
            name=name,
            blend=blend,
            span=span,
            plugin_id=plugin_id,
            plugin_params=dict(plugin_params or {}),
        )
        ch.layers.append(layer)
        ch._invalidate_cache()
        self._emit_structure()
        return layer

    def flatten_layer(self, layer: Layer) -> None:
        """Bake ``layer`` and every layer beneath it into a single base layer,
        preserving the layers above it. One undo step.

        Well-defined 'commit' for a generated preview layer: the composite of
        layers[0..k] (with their blend/span/fade envelopes) becomes the new base,
        and layers above k keep stacking on top exactly as before.
        """
        found = self._find_layer(layer)
        if found is None:
            return
        from wombat.domain.synthesis import synthesize
        ch, k = found
        baked = synthesize(ch.layers[: k + 1])
        ch_idx = self._channel_index(ch)
        ali = self._active_layer_indices.get(ch_idx, 0) if ch_idx is not None else 0
        self._undo.snapshot_structural("Flatten layer", ch, ali, self.selection)
        above = ch.layers[k + 1 :]
        base = Layer(actions=baked, name=ch.layers[0].name)
        ch.layers = [base] + above
        if ch_idx is not None:
            self._active_layer_indices[ch_idx] = min(ali, len(ch.layers) - 1)
        ch._invalidate_cache()
        self._emit_structure()

    def plugin_edit_begin(self, layer: Layer, label: str) -> bool:
        """Open a one-undo-step edit of ``layer`` for plugin code.

        Returns False if the layer is no longer in the project (detached), in
        which case the caller should treat the edit session as a no-op.
        """
        found = self._find_layer(layer)
        if found is None:
            return False
        ch, i = found
        self._undo.snapshot(label, [(ch, i)], self.selection)
        return True

    def plugin_edit_end(self, layer: Layer) -> None:
        """Close a plugin edit: invalidate cache and emit a single repaint signal."""
        found = self._find_layer(layer)
        if found is None:
            return
        ch, _ = found
        ch._invalidate_cache()
        self._emit_actions()

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
