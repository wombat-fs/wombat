"""Event model — dataclasses for EventLibrary, EventDefinition, Step, NormalizationConfig.

No Qt, no mpv imports. Domain-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NormalizationConfig:
    """Per-axis normalization settings from the YAML `normalization` block.

    Normalizes raw parameter values (Hz, %, etc.) to [0, 1] range following
    the rules from FUNDAMENTAL_OPERATIONS.md:
      1. max == 1.0 → already normalized; pass through
      2. max > 1.0 and |value| ≤ 1.0 → assumed pre-normalized; pass through
      3. otherwise → value / max
    """
    axes: dict[str, tuple[float, str]]   # axis_name -> (max, unit)

    def normalize(self, axis: str, value: float) -> float:
        """Return value normalized to [0, 1]. Unknown axes pass through."""
        if axis not in self.axes:
            return value
        max_val, _ = self.axes[axis]
        if max_val == 1.0:
            return value
        if max_val > 1.0 and abs(value) <= 1.0:
            return value  # assumed pre-normalized
        return value / max_val

    def to_pos(self, axis: str, value: float, center: int = 0) -> int:
        """Normalize value and map to integer pos units relative to center."""
        return int(round(center + self.normalize(axis, value) * 100))


@dataclass
class Step:
    """One operation within an event, with resolved params (no $vars)."""
    operation: str
    axes: list[str]
    start_offset_ms: int = 0    # ms after event start_ms
    params: dict = field(default_factory=dict)


@dataclass
class EventDefinition:
    name: str
    default_params: dict
    steps: list[Step]


@dataclass
class EventGroup:
    name: str
    prefix: str
    description: str = ""


@dataclass
class EventLibrary:
    normalization: NormalizationConfig
    events: dict[str, EventDefinition]
    groups: list[EventGroup] = field(default_factory=list)
