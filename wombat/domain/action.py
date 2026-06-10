"""Action and ActionList — the core funscript data container.

ActionList is kept sorted by `at` (seconds), unique per timestamp.
Insert at an existing `at` replaces the existing action.
All lookups are O(log n) via bisect over a cached keys list.
"""
from __future__ import annotations

import bisect
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True, order=False)
class Action:
    """A single haptic action: time in seconds + position 0–100."""

    at: float   # seconds (ms only at file I/O)
    pos: int    # 0–100

    def __post_init__(self) -> None:
        object.__setattr__(self, "pos", max(0, min(100, int(self.pos))))


class ActionList:
    """Sorted-by-time, unique-by-time container of Actions.

    Backed by a plain list kept in sorted order. A parallel ``_keys``
    list of ``at`` values makes bisect lookups O(log n) without hashing.
    """

    __slots__ = ("_actions", "_keys")

    def __init__(self, actions: Iterable[Action] = ()) -> None:
        self._actions: list[Action] = []
        self._keys: list[float] = []
        for a in actions:
            self.add(a)

    # ----------------------------------------------------------------- sequence

    def __len__(self) -> int:
        return len(self._actions)

    def __iter__(self) -> Iterator[Action]:
        return iter(self._actions)

    def __getitem__(self, i: int) -> Action:
        return self._actions[i]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ActionList):
            return self._actions == other._actions
        return NotImplemented

    def __repr__(self) -> str:
        return f"ActionList({self._actions!r})"

    # ------------------------------------------------------------------ editing

    def add(self, action: Action) -> None:
        """Insert action; replaces any existing action at the same timestamp."""
        i = bisect.bisect_left(self._keys, action.at)
        if i < len(self._keys) and self._keys[i] == action.at:
            self._actions[i] = action
        else:
            self._actions.insert(i, action)
            self._keys.insert(i, action.at)

    def remove(self, action: Action) -> None:
        """Remove by identity (at + pos). Raises ValueError if not found."""
        i = bisect.bisect_left(self._keys, action.at)
        if i < len(self._keys) and self._actions[i] == action:
            del self._actions[i]
            del self._keys[i]
        else:
            raise ValueError(f"Action not found: {action}")

    def remove_at(self, at: float) -> None:
        """Remove the action at exactly this timestamp. Raises ValueError if absent."""
        i = bisect.bisect_left(self._keys, at)
        if i < len(self._keys) and self._keys[i] == at:
            del self._actions[i]
            del self._keys[i]
        else:
            raise ValueError(f"No action at t={at}")

    # ------------------------------------------------------------------ lookups

    def at_time(self, t: float, max_error: float) -> Action | None:
        """Return the nearest action within ±max_error of t, or None."""
        if not self._keys:
            return None
        i = bisect.bisect_left(self._keys, t)
        best: Action | None = None
        best_dist = max_error + 1.0
        for j in (i - 1, i):
            if 0 <= j < len(self._actions):
                d = abs(self._keys[j] - t)
                if d <= max_error and d < best_dist:
                    best = self._actions[j]
                    best_dist = d
        return best

    def closest(self, t: float) -> Action | None:
        """Return the nearest action by time, any distance."""
        if not self._keys:
            return None
        i = bisect.bisect_left(self._keys, t)
        if i == 0:
            return self._actions[0]
        if i >= len(self._actions):
            return self._actions[-1]
        before = self._actions[i - 1]
        after = self._actions[i]
        return before if (t - before.at) <= (after.at - t) else after

    def next_after(self, t: float) -> Action | None:
        """First action with at > t."""
        i = bisect.bisect_right(self._keys, t)
        return self._actions[i] if i < len(self._actions) else None

    def before(self, t: float) -> Action | None:
        """Last action with at < t."""
        i = bisect.bisect_left(self._keys, t) - 1
        return self._actions[i] if i >= 0 else None

    def index_range(self, t0: float, t1: float) -> tuple[int, int]:
        """Return [lo, hi) index range of actions whose at is in [t0, t1]."""
        lo = bisect.bisect_left(self._keys, t0)
        hi = bisect.bisect_right(self._keys, t1)
        return lo, hi

    # ----------------------------------------------------------- numpy interface

    def to_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (at: float64, pos: int32) arrays, sorted by time."""
        if not self._actions:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.int32)
        at = np.fromiter((a.at for a in self._actions), dtype=np.float64, count=len(self._actions))
        pos = np.fromiter((a.pos for a in self._actions), dtype=np.int32, count=len(self._actions))
        return at, pos

    @classmethod
    def from_arrays(cls, at: np.ndarray, pos: np.ndarray) -> ActionList:
        """Build an ActionList from parallel at (float64) and pos (int32) arrays."""
        al = cls.__new__(cls)
        al._actions = []
        al._keys = []
        for t, p in zip(at.astype(np.float64), pos.astype(np.int32)):
            al.add(Action(float(t), int(p)))
        return al

    def copy(self) -> ActionList:
        al = ActionList.__new__(ActionList)
        al._actions = self._actions.copy()
        al._keys = self._keys.copy()
        return al
