"""Synthesis engine — folds a layer stack into a flat ActionList.

No Qt, no mpv imports. Pure domain logic, fully headless-testable.

Algorithm:
  1. Determine min_fade from fps or resolution_hz.
  2. Collect fade-ramp windows for all spanned enabled layers.
  3. Build sample-time set:
       • exact action-time breakpoints outside every fade window
       • dense samples (frame-aligned when fps given) inside fade windows
  4. Evaluate the bottom-to-top fold at each sample time.
  5. RDP-simplify the dense-window runs; leave exact breakpoints intact.

Identity: a single full-span (span=None), override, no-fade layer returns
its actions unchanged (shortcut path before any resample).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from wombat.domain.action import Action, ActionList
from wombat.domain.channel import BlendMode, FadeCurve, Layer
from wombat.domain.interpolate import values_at as _values_at


# ------------------------------------------------------------------ params

@dataclass(frozen=True)
class SynthesisParams:
    resolution_hz: float = 60.0       # dense sampling rate inside fade windows
    simplify_epsilon: float = 0.5     # RDP epsilon (pos units) for dense regions
    fps: float | None = None          # frame-align dense samples; sets min_fade


# Module-level default — overridden by preferences at app startup.
_default_params: SynthesisParams = SynthesisParams()


def get_default_params() -> SynthesisParams:
    """Return the currently active default SynthesisParams."""
    return _default_params


def set_default_params(params: SynthesisParams) -> None:
    """Override the module-level default (called from preferences)."""
    global _default_params
    _default_params = params


# ------------------------------------------------------------------ public API

def synthesize(layers: list[Layer], params: SynthesisParams | None = None) -> ActionList:
    """Fold a layer stack into a flat ActionList."""
    if params is None:
        params = SynthesisParams()

    enabled = [l for l in layers if l.enabled]
    if not enabled:
        return ActionList()

    # Identity shortcut — single full-span override with no fades
    if (
        len(enabled) == 1
        and enabled[0].blend == BlendMode.OVERRIDE
        and enabled[0].span is None
        and enabled[0].fade_in == 0.0
        and enabled[0].fade_out == 0.0
    ):
        return enabled[0].actions.copy()

    min_fade = 1.0 / params.fps if params.fps else 1.0 / params.resolution_hz

    # Collect all fade-ramp windows (intervals where weight is non-constant)
    raw_fade_windows: list[tuple[float, float]] = []
    for layer in enabled:
        raw_fade_windows.extend(_layer_fade_intervals(layer, min_fade))
    merged_fades = _merge_intervals(raw_fade_windows)

    # Build exact breakpoint set (action times outside all fade windows)
    exact_times: set[float] = set()
    for layer in enabled:
        for a in layer.actions:
            if not _in_any_interval(a.at, merged_fades):
                exact_times.add(a.at)
    # Always include fade-window boundaries as exact breakpoints
    for fs, fe in merged_fades:
        exact_times.add(fs)
        exact_times.add(fe)

    # Dense samples inside each fade window
    dense_arrays: list[np.ndarray] = [
        _dense_samples(fs, fe, params.resolution_hz, params.fps)
        for fs, fe in merged_fades
    ]
    dense_time_set: set[float] = set()
    for arr in dense_arrays:
        dense_time_set.update(arr.tolist())

    # Merge all times and sort
    all_time_set = exact_times | dense_time_set
    if not all_time_set:
        return ActionList()
    t_arr = np.array(sorted(all_time_set), dtype=np.float64)

    # Evaluate fold
    result_pos = _evaluate_fold(enabled, t_arr, min_fade)
    pos_arr = np.clip(np.round(result_pos), 0, 100).astype(np.int32)

    full_al = ActionList(
        Action(float(t), int(p)) for t, p in zip(t_arr.tolist(), pos_arr.tolist())
    )

    # RDP-simplify dense regions only
    if merged_fades and params.simplify_epsilon > 0 and dense_time_set:
        return _selective_rdp(full_al, dense_time_set, params.simplify_epsilon)
    return full_al


# ------------------------------------------------------------------ fold evaluation

def _evaluate_fold(enabled: list[Layer], t_arr: np.ndarray, min_fade: float) -> np.ndarray:
    """Bottom-to-top fold of all enabled layers at sample times."""
    result = np.zeros(len(t_arr), dtype=np.float64)
    for layer in enabled:
        w = _weight_at_array(layer, t_arr, min_fade)
        active = w > 0
        if not np.any(active):
            continue
        v = _values_at(layer.actions, t_arr)
        if layer.blend == BlendMode.OVERRIDE:
            # lerp(result, v, w)  →  result + w*(v - result)
            result = result + w * (v - result)
        elif layer.blend == BlendMode.MULTIPLY:
            # Scale the accumulated signal around the layer's center by the layer
            # value as a 0..1 factor, weight-blended. factor=1 → no change;
            # factor=0 → collapse to center. With center=0 this is plain scaling
            # toward zero (natural for volume-style channels); with center=50 it
            # damps oscillations toward the midpoint.
            factor = v / 100.0
            result = result + w * (result - layer.center) * (factor - 1.0)
        else:  # ADDITIVE
            result = result + w * (v - layer.center)
    return result


def _weight_at_array(layer: Layer, t_arr: np.ndarray, min_fade: float) -> np.ndarray:
    """Vectorised weight envelope for a layer over t_arr."""
    if layer.span is None:
        return np.ones(len(t_arr), dtype=np.float64)

    start, end = layer.span
    total = end - start
    eff_fi = max(min_fade, layer.fade_in)
    eff_fo = max(min_fade, layer.fade_out)
    if total > 0 and eff_fi + eff_fo > total:
        ratio = eff_fi / (eff_fi + eff_fo)
        eff_fi = total * ratio
        eff_fo = total - eff_fi

    w = np.zeros(len(t_arr), dtype=np.float64)
    inside = (t_arr >= start) & (t_arr <= end)
    if not np.any(inside):
        return w

    t_in = t_arr[inside]
    w_in = np.ones(len(t_in), dtype=np.float64)

    if eff_fi > 0:
        fi_mask = t_in < start + eff_fi
        if np.any(fi_mask):
            frac = (t_in[fi_mask] - start) / eff_fi
            w_in[fi_mask] = _curve_array(frac, layer.fade_curve)

    if eff_fo > 0:
        fo_mask = t_in > end - eff_fo
        if np.any(fo_mask):
            frac = (end - t_in[fo_mask]) / eff_fo
            w_in[fo_mask] = _curve_array(frac, layer.fade_curve)

    w[inside] = w_in
    return w


def _curve_array(frac: np.ndarray, curve: FadeCurve) -> np.ndarray:
    frac = np.clip(frac, 0.0, 1.0)
    if curve == FadeCurve.SMOOTH:
        return frac * frac * (3.0 - 2.0 * frac)
    return frac


# ------------------------------------------------------------------ sampling helpers

def _layer_fade_intervals(layer: Layer, min_fade: float) -> list[tuple[float, float]]:
    """Return intervals where this layer's weight is ramping (non-constant)."""
    if layer.span is None:
        return []
    start, end = layer.span
    total = end - start
    eff_fi = max(min_fade, layer.fade_in)
    eff_fo = max(min_fade, layer.fade_out)
    if total > 0 and eff_fi + eff_fo > total:
        ratio = eff_fi / (eff_fi + eff_fo)
        eff_fi = total * ratio
        eff_fo = total - eff_fi
    result: list[tuple[float, float]] = []
    if eff_fi > 0:
        result.append((start, start + eff_fi))
    if eff_fo > 0:
        result.append((end - eff_fo, end))
    return result


def _dense_samples(
    t_start: float, t_end: float, resolution_hz: float, fps: float | None
) -> np.ndarray:
    """Dense sample array inside [t_start, t_end], frame-aligned if fps given."""
    if fps is not None and fps > 0:
        dt = 1.0 / fps
        first = math.ceil(t_start / dt) * dt
    else:
        dt = 1.0 / resolution_hz
        first = t_start
    times = np.arange(first, t_end + dt * 0.5, dt)
    return times[(times >= t_start - 1e-9) & (times <= t_end + 1e-9)]


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping/adjacent intervals, return sorted list."""
    if not intervals:
        return []
    sorted_iv = sorted(intervals)
    merged: list[tuple[float, float]] = [sorted_iv[0]]
    for s, e in sorted_iv[1:]:
        ms, me = merged[-1]
        if s <= me:
            merged[-1] = (ms, max(me, e))
        else:
            merged.append((s, e))
    return merged


def _in_any_interval(t: float, intervals: list[tuple[float, float]]) -> bool:
    for s, e in intervals:
        if s <= t <= e:
            return True
    return False


# ------------------------------------------------------------------ selective RDP

def _selective_rdp(
    al: ActionList, dense_times: set[float], epsilon: float
) -> ActionList:
    """RDP-simplify contiguous dense runs; leave exact breakpoints intact.

    Each dense run is simplified with its two bounding exact points as anchors
    so the result is continuous with the sparse segments on either side.
    """
    from wombat.domain.transforms import simplify_rdp

    points = list(al)
    n = len(points)
    if n == 0:
        return al

    keep: set[int] = set()
    i = 0
    while i < n:
        if points[i].at not in dense_times:
            keep.add(i)
            i += 1
        else:
            # Find extent of this dense run
            j = i
            while j < n and points[j].at in dense_times:
                j += 1
            # Include bounding exact points as anchors
            start = max(0, i - 1)
            end = min(n - 1, j)
            sub = ActionList(points[k] for k in range(start, end + 1))
            simplified = simplify_rdp(sub, epsilon)
            simplified_ats = frozenset(a.at for a in simplified)
            for k in range(start, end + 1):
                if points[k].at in simplified_ats:
                    keep.add(k)
            i = j

    return ActionList(points[k] for k in sorted(keep))
