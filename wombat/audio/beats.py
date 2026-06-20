"""Beat grids — detected musical beats/downbeats and the ``.beats`` format.

A ``BeatGrid`` is the in-memory model shared by audio beat detection, the
timeline overlay, snap-to-beat, and the snippet rhythm system.  The ``.beats``
file format (tab-separated ``time<TAB>count``, time in seconds, count 1 = downbeat)
is its serialization, so import/export and detection feed the same path.

This module is headless and dependency-light (numpy only).  The detection
service that runs the external ``beat_this_cpp`` binary lives separately so this
stays trivially testable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# count value meaning "position within bar unknown" (single-column .beats input)
UNKNOWN_COUNT = 0
DOWNBEAT_COUNT = 1


@dataclass(frozen=True)
class BeatGrid:
    """Sorted beat timestamps with per-beat bar position.

    ``times`` are seconds (float64), strictly the order they should display in.
    ``counts`` parallels ``times``: 1 = downbeat, 2..N = other beats within the
    bar, 0 = unknown.  Construct via the class so invariants (matching lengths,
    sorted, correct dtypes) hold; helpers below preserve them.
    """

    times: np.ndarray   # float64 seconds, sorted ascending
    counts: np.ndarray  # int32, 1 = downbeat, 2..N = beat-in-bar, 0 = unknown

    def __post_init__(self) -> None:
        times = np.asarray(self.times, dtype=np.float64).reshape(-1)
        counts = np.asarray(self.counts, dtype=np.int32).reshape(-1)
        if len(times) != len(counts):
            raise ValueError(
                f"times/counts length mismatch: {len(times)} != {len(counts)}"
            )
        if len(times) > 1 and np.any(np.diff(times) < 0):
            order = np.argsort(times, kind="stable")
            times = times[order]
            counts = counts[order]
        # frozen dataclass: bypass the immutability guard to store normalized arrays
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "counts", counts)

    @classmethod
    def empty(cls) -> "BeatGrid":
        return cls(np.empty(0, dtype=np.float64), np.empty(0, dtype=np.int32))

    def __len__(self) -> int:
        return len(self.times)

    @property
    def downbeats(self) -> np.ndarray:
        """Timestamps where count == 1 (bar starts)."""
        return self.times[self.counts == DOWNBEAT_COUNT]

    def in_span(self, t0: float, t1: float) -> "BeatGrid":
        """Sub-grid of beats with ``t0 <= time <= t1`` (order preserved)."""
        if len(self.times) == 0:
            return self
        lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
        mask = (self.times >= lo) & (self.times <= hi)
        return BeatGrid(self.times[mask], self.counts[mask])

    def nearest(self, t: float) -> float | None:
        """Timestamp of the beat closest to ``t``, or ``None`` if empty."""
        if len(self.times) == 0:
            return None
        i = int(np.searchsorted(self.times, t))
        # candidates straddling t: index i-1 and i (clamped)
        best: float | None = None
        best_d = float("inf")
        for j in (i - 1, i):
            if 0 <= j < len(self.times):
                d = abs(float(self.times[j]) - t)
                if d < best_d:
                    best_d = d
                    best = float(self.times[j])
        return best


def parse_beats(text: str) -> BeatGrid:
    """Parse ``.beats`` text into a ``BeatGrid``.

    Each non-blank line is ``time`` optionally followed by whitespace and a
    ``count``.  Whitespace-separated so both tab- and space-delimited files work.
    Lines without a parseable leading float are skipped (e.g. comments/headers).
    A missing or non-integer count becomes ``UNKNOWN_COUNT``.
    """
    times: list[float] = []
    counts: list[int] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        try:
            t = float(parts[0])
        except ValueError:
            continue
        count = UNKNOWN_COUNT
        if len(parts) > 1:
            try:
                count = int(float(parts[1]))
            except ValueError:
                count = UNKNOWN_COUNT
        times.append(t)
        counts.append(count)
    return BeatGrid(
        np.asarray(times, dtype=np.float64),
        np.asarray(counts, dtype=np.int32),
    )


def serialize_beats(grid: BeatGrid) -> str:
    """Serialize a ``BeatGrid`` to ``.beats`` text (tab-separated, trailing newline).

    Times are written with millisecond precision; ``UNKNOWN_COUNT`` beats are
    written as a single column so the file round-trips through ``parse_beats``.
    """
    lines: list[str] = []
    for t, c in zip(grid.times, grid.counts):
        if int(c) == UNKNOWN_COUNT:
            lines.append(f"{float(t):.3f}")
        else:
            lines.append(f"{float(t):.3f}\t{int(c)}")
    return "\n".join(lines) + ("\n" if lines else "")
