"""Linear interpolation over an ActionList.

Linear is the canonical funscript semantic — devices move linearly between
actions. Spline is a rendering nicety deferred to later.

Empty ActionList behavior: value_at returns 0.0.
"""
from __future__ import annotations

import numpy as np

from wombat.domain.action import ActionList


def value_at(actions: ActionList, t: float) -> float:
    """Linear interpolation at time t (seconds).

    - Empty list → 0.0
    - Before first action → first action's pos (clamp)
    - After last action → last action's pos (clamp)
    - Between two actions → linear interpolation
    - Exactly at an action → that action's pos

    Uses np.interp to stay consistent with values_at at all edge cases,
    including exact timestamp hits where before()/next_after() would skip
    the matching action and interpolate over the wrong bracket.
    """
    if len(actions) == 0:
        return 0.0
    at, pos = actions.to_arrays()
    return float(np.interp(t, at, pos.astype(np.float64)))


def values_at(actions: ActionList, times: np.ndarray) -> np.ndarray:
    """Vectorized linear interpolation at multiple time points.

    Uses np.interp which clamps at endpoints — matches value_at semantics.
    """
    if len(actions) == 0:
        return np.zeros(len(times), dtype=np.float64)

    at, pos = actions.to_arrays()
    result: np.ndarray = np.interp(times, at, pos.astype(np.float64))
    return result
