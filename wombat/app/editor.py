"""EditorController — the single funnel for all funscript mutations.

All writes go through here: snapshot undo, mutate the active layer,
invalidate the synthesis cache, emit signals so the timeline repaints.

Selection is per-channel: switching active channel preserves each channel's
selection and restores the new channel's previous selection.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from wombat.app.undo import UndoStack
from wombat.domain.action import Action, ActionList
from wombat.domain.channel import Channel

if __debug__:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from wombat.app.project import Project
        from wombat.playback.player import VideoPlayer


class EditorController(QObject):
    actions_changed = Signal()      # a channel's actions mutated → repaint / re-export
    selection_changed = Signal()
    history_changed = Signal()      # can_undo / can_redo may have changed

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
        self._selections: dict[int, frozenset[float]] = {}  # per-channel
        self._clipboard: list[Action] = []
        self._snap_to_frame: bool = False
        # gesture state
        self._pre_move_snapshot: ActionList = ActionList()
        self._pre_move_selection: frozenset[float] = frozenset()

    # ----------------------------------------------------------------- project

    def set_project(self, project: Project) -> None:
        self._project = project
        self._active_idx = 0
        self._selections = {}
        self._clipboard = []
        self._pre_move_snapshot = ActionList()
        self._pre_move_selection = frozenset()

    # ----------------------------------------------------------------- active

    @property
    def has_active_channel(self) -> bool:
        return 0 <= self._active_idx < len(self._project.channels)

    @property
    def active_channel(self) -> Channel:
        return self._project.channels[self._active_idx]

    @property
    def active_layer_index(self) -> int:
        return 0  # base layer; Phase 6 will expose layer selection

    def set_active_channel_index(self, index: int) -> None:
        self._active_idx = index
        self.selection_changed.emit()

    def _layer(self) -> ActionList:
        return self.active_channel.layers[self.active_layer_index].actions

    def _targets(self) -> list[tuple[Channel, int]]:
        return [(self.active_channel, self.active_layer_index)]

    # ----------------------------------------------------------------- selection

    @property
    def selection(self) -> frozenset[float]:
        return self._selections.get(self._active_idx, frozenset())

    def _set_selection(self, s: frozenset[float]) -> None:
        self._selections[self._active_idx] = s

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
        """Delete all selected actions in one undo step."""
        if not self.has_active_channel or not self.selection:
            return
        self._undo.snapshot("Delete selection", self._targets(), self.selection)
        layer = self._layer()
        for at in list(self.selection):
            try:
                layer.remove_at(at)
            except ValueError:
                pass
        self._set_selection(frozenset())
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
                new_at = a.at + d_seconds
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

    # ----------------------------------------------------------------- history

    def undo(self) -> None:
        entry = self._undo.undo(self.selection)
        if entry is not None:
            for snap in entry.snapshots:
                ch_idx = self._channel_index(snap.channel)
                if ch_idx is not None:
                    self._selections[ch_idx] = snap.selection
            self._emit_actions()
            self.selection_changed.emit()
            self.history_changed.emit()

    def redo(self) -> None:
        entry = self._undo.redo(self.selection)
        if entry is not None:
            for snap in entry.snapshots:
                ch_idx = self._channel_index(snap.channel)
                if ch_idx is not None:
                    self._selections[ch_idx] = snap.selection
            self._emit_actions()
            self.selection_changed.emit()
            self.history_changed.emit()

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
