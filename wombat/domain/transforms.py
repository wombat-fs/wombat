"""Pure ActionList transforms — all return new ActionLists, no mutation.

Composes with snapshot-based undo: callers snapshot the layer before applying.
"""
from __future__ import annotations

import numpy as np

from wombat.domain.action import Action, ActionList


def invert(actions: ActionList, range_: int = 100) -> ActionList:
    """Flip positions: pos → range_ - pos."""
    return ActionList(Action(a.at, range_ - a.pos) for a in actions)


def offset_time(actions: ActionList, seconds: float) -> ActionList:
    """Shift all timestamps by `seconds` (may go negative — callers clamp if needed)."""
    return ActionList(Action(a.at + seconds, a.pos) for a in actions)


def offset_pos(actions: ActionList, delta: int) -> ActionList:
    """Add delta to every pos, clamped to 0–100."""
    return ActionList(Action(a.at, max(0, min(100, a.pos + delta))) for a in actions)


def scale_pos(actions: ActionList, factor: float, pivot: int = 50) -> ActionList:
    """Scale positions around a pivot point, clamped to 0–100."""
    if not actions:
        return ActionList()
    at, pos = actions.to_arrays()
    scaled = np.clip(np.round(pivot + (pos - pivot) * factor), 0, 100).astype(np.int32)
    return ActionList.from_arrays(at, scaled)


def simplify_rdp(actions: ActionList, epsilon: float) -> ActionList:
    """Ramer–Douglas–Peucker simplification on the (at, pos) polyline.

    epsilon is in pos units (0–100 scale). Always keeps first and last action.
    """
    if len(actions) <= 2:
        return actions.copy()

    at, pos = actions.to_arrays()
    keep = _rdp_indices(at, pos.astype(np.float64), epsilon)
    return ActionList(actions[i] for i in keep)


def _rdp_indices(at: np.ndarray, pos: np.ndarray, epsilon: float) -> list[int]:
    """Return sorted indices of points to keep (recursive RDP)."""
    n = len(at)
    if n <= 2:
        return list(range(n))

    stack = [(0, n - 1)]
    keep = {0, n - 1}

    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2:
            continue

        # Perpendicular distance from each interior point to the line lo→hi.
        # We normalise time to the same scale as pos by using the actual coordinate
        # values. The line is defined in (at, pos) space.
        at0, pos0 = at[lo], pos[lo]
        at1, pos1 = at[hi], pos[hi]

        dat = at1 - at0
        dpos = pos1 - pos0
        seg_len = (dat**2 + dpos**2) ** 0.5

        if seg_len == 0.0:
            # All points in this segment are at the same time → keep nothing in between
            continue

        idx = np.arange(lo + 1, hi)
        # Perpendicular distances
        cross = np.abs(dpos * (at[idx] - at0) - dat * (pos[idx] - pos0))
        dists = cross / seg_len

        max_i = int(np.argmax(dists))
        max_dist = float(dists[max_i])
        split = lo + 1 + max_i

        if max_dist > epsilon:
            keep.add(split)
            stack.append((lo, split))
            stack.append((split, hi))

    return sorted(keep)


def equalize(actions: ActionList) -> ActionList:
    """Redistribute timestamps evenly between first and last, preserving positions.

    Positions stay in their original order; only the timing is equalized.
    Single or empty lists are returned unchanged.
    """
    if len(actions) <= 1:
        return actions.copy()

    t0 = actions[0].at
    t1 = actions[-1].at
    n = len(actions)
    step = (t1 - t0) / (n - 1)
    return ActionList(
        Action(t0 + i * step, actions[i].pos) for i in range(n)
    )


def top_points(actions: ActionList) -> ActionList:
    """Local maxima (points higher than both neighbours)."""
    if len(actions) < 3:
        return actions.copy()
    result = [actions[0]]
    for i in range(1, len(actions) - 1):
        if actions[i].pos >= actions[i - 1].pos and actions[i].pos >= actions[i + 1].pos:
            result.append(actions[i])
    result.append(actions[-1])
    return ActionList(result)


def bottom_points(actions: ActionList) -> ActionList:
    """Local minima (points lower than both neighbours)."""
    if len(actions) < 3:
        return actions.copy()
    result = [actions[0]]
    for i in range(1, len(actions) - 1):
        if actions[i].pos <= actions[i - 1].pos and actions[i].pos <= actions[i + 1].pos:
            result.append(actions[i])
    result.append(actions[-1])
    return ActionList(result)


def mid_points(actions: ActionList) -> ActionList:
    """Points that are neither local maxima nor local minima."""
    if len(actions) < 3:
        return actions.copy()
    result = [actions[0]]
    for i in range(1, len(actions) - 1):
        p_prev, p_cur, p_next = actions[i - 1].pos, actions[i].pos, actions[i + 1].pos
        is_top = p_cur >= p_prev and p_cur >= p_next
        is_bot = p_cur <= p_prev and p_cur <= p_next
        if not is_top and not is_bot:
            result.append(actions[i])
    result.append(actions[-1])
    return ActionList(result)
