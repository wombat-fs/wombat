"""UndoStack — snapshot-based, transaction-bracketed, multi-channel-ready.

Usage:
  Discrete action edit:  stack.snapshot(desc, targets, sel) → mutate → done
  Gesture (drag):        stack.begin(desc, targets, sel) → mutate repeatedly
                         → stack.commit()  (one undo step) or stack.cancel()
  Structural layer op:   stack.snapshot_structural(desc, channel, ali, sel) → mutate → done
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from wombat.domain.action import ActionList
from wombat.domain.channel import Channel, Layer


@dataclass
class LayerSnapshot:
    """Captures one layer's actions (for action-level edits)."""
    channel: Channel
    layer_index: int
    actions: ActionList       # deep copy at snapshot time
    selection: frozenset[float]


@dataclass
class StructuralSnapshot:
    """Captures the full layer list (for structural ops: add/remove/reorder)."""
    channel: Channel
    layers: list[Layer]       # deep copy of ALL layers
    active_layer_index: int   # the pre-op active layer index
    selection: frozenset[float]


@dataclass
class UndoEntry:
    description: str
    snapshots: list[LayerSnapshot]
    structural: list[StructuralSnapshot] = field(default_factory=list)


def _deep_copy_layers(layers: list[Layer]) -> list[Layer]:
    return copy.deepcopy(layers)


class UndoStack:
    def __init__(self) -> None:
        self._undo: list[UndoEntry] = []
        self._redo: list[UndoEntry] = []
        self._pending: UndoEntry | None = None

    # ------------------------------------------------------------------ helpers

    def _make_snapshots(
        self,
        targets: list[tuple[Channel, int]],
        selection: frozenset[float],
    ) -> list[LayerSnapshot]:
        return [
            LayerSnapshot(ch, li, ch.layers[li].actions.copy(), selection)
            for ch, li in targets
        ]

    def _capture_current(
        self, entry: UndoEntry, selection: frozenset[float]
    ) -> UndoEntry:
        snaps = [
            LayerSnapshot(
                s.channel,
                s.layer_index,
                s.channel.layers[s.layer_index].actions.copy(),
                selection,
            )
            for s in entry.snapshots
        ]
        struct = [
            StructuralSnapshot(
                s.channel,
                _deep_copy_layers(s.channel.layers),
                s.active_layer_index,
                selection,
            )
            for s in entry.structural
        ]
        return UndoEntry(entry.description, snaps, struct)

    @staticmethod
    def _restore(entry: UndoEntry) -> None:
        for s in entry.snapshots:
            s.channel.layers[s.layer_index].actions = s.actions.copy()
            s.channel._invalidate_cache()
        for ss in entry.structural:
            ss.channel.layers = _deep_copy_layers(ss.layers)
            ss.channel._invalidate_cache()

    # ------------------------------------------------------------------ public

    def snapshot(
        self,
        description: str,
        targets: list[tuple[Channel, int]],
        selection: frozenset[float],
    ) -> None:
        """Capture pre-edit state as one complete undo entry; clears redo."""
        self._undo.append(UndoEntry(description, self._make_snapshots(targets, selection)))
        self._redo.clear()

    def snapshot_structural(
        self,
        description: str,
        channel: Channel,
        active_layer_index: int,
        selection: frozenset[float],
    ) -> None:
        """Capture pre-structural-edit state (entire layer list)."""
        snap = StructuralSnapshot(
            channel=channel,
            layers=_deep_copy_layers(channel.layers),
            active_layer_index=active_layer_index,
            selection=selection,
        )
        self._undo.append(UndoEntry(description, [], [snap]))
        self._redo.clear()

    def snapshot_multi_structural(
        self,
        description: str,
        channels: list[tuple[Channel, int]],
        selection: frozenset[float],
    ) -> None:
        """Capture pre-structural-edit state for multiple channels as one undo entry."""
        snaps = [
            StructuralSnapshot(ch, _deep_copy_layers(ch.layers), ali, selection)
            for ch, ali in channels
        ]
        self._undo.append(UndoEntry(description, [], snaps))
        self._redo.clear()

    def begin(
        self,
        description: str,
        targets: list[tuple[Channel, int]],
        selection: frozenset[float],
    ) -> None:
        """Start a gesture — pre-gesture state captured once."""
        self._pending = UndoEntry(description, self._make_snapshots(targets, selection))

    def begin_structural(
        self,
        description: str,
        channel: Channel,
        active_layer_index: int,
        selection: frozenset[float],
    ) -> None:
        """Start a structural gesture — captures entire layer list once."""
        snap = StructuralSnapshot(
            channel=channel,
            layers=_deep_copy_layers(channel.layers),
            active_layer_index=active_layer_index,
            selection=selection,
        )
        self._pending = UndoEntry(description, [], [snap])

    def commit(self) -> None:
        """Finalise the in-progress gesture as one undo entry."""
        if self._pending is not None:
            self._undo.append(self._pending)
            self._redo.clear()
            self._pending = None

    def cancel(self) -> None:
        """Abort the gesture and restore pre-gesture state."""
        if self._pending is not None:
            self._restore(self._pending)
            self._pending = None

    def undo(self, current_selection: frozenset[float] = frozenset()) -> UndoEntry | None:
        """Restore pre-edit state; push inverse (current state) onto redo."""
        if not self._undo:
            return None
        entry = self._undo.pop()
        self._redo.append(self._capture_current(entry, current_selection))
        self._restore(entry)
        return entry

    def redo(self, current_selection: frozenset[float] = frozenset()) -> UndoEntry | None:
        """Re-apply a previously undone edit; push current state onto undo."""
        if not self._redo:
            return None
        entry = self._redo.pop()
        self._undo.append(self._capture_current(entry, current_selection))
        self._restore(entry)
        return entry

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def descriptions(self) -> tuple[list[str], list[str]]:
        """Return (undo_descs, redo_descs) for an optional history panel."""
        return (
            [e.description for e in self._undo],
            [e.description for e in self._redo],
        )
