"""Translate EventDefinition steps into Wombat Layer insertions.

Each operation type has a per-type translator that builds a Layer. The
apply_event() entry point collects (channel_name, Layer) pairs — the caller
(EditorController.apply_event_layers) handles the undo transaction and
multi-channel insertion.

Blend model:
  apply_modulation / apply_linear_change mode=additive  → BlendMode.ADDITIVE, center=50
  apply_modulation / apply_linear_change mode=overwrite → BlendMode.OVERRIDE

Value encoding for ADDITIVE layers:
  contribution = normalized_value * 100
  stored_pos = clamp(50 + contribution, 0, 100)
  synthesis: result += w * (stored_pos - 50) / 100 * 100   → adds contribution

No Qt, no mpv imports.
"""
from __future__ import annotations

import logging
import warnings
from collections.abc import Callable
from typing import Literal, cast

from wombat.domain.action import Action, ActionList
from wombat.domain.channel import BlendMode, Layer
from wombat.domain.events.model import EventDefinition, EventLibrary, Step
from wombat.domain.snippets.base import WaveformSnippet

log = logging.getLogger(__name__)

_WAVEFORM_MAP = {
    "sin": "sine",
    "sine": "sine",
    "square": "square",
    "triangle": "triangle",
    "sawtooth": "sawtooth",
}

# ------------------------------------------------------------------ translators


def _translate_modulation(
    step: Step, axis: str, span: tuple[float, float], lib: EventLibrary, group: str | None
) -> Layer:
    p = step.params
    norm = lib.normalization

    waveform = cast(
        Literal["sine", "triangle", "square", "sawtooth"],
        _WAVEFORM_MAP.get(str(p.get("waveform", "sin")), "sine"),
    )
    freq = float(p.get("frequency", 1.0))
    amp_norm = norm.normalize(axis, float(p.get("amplitude", 0.0)))
    mlo_norm = norm.normalize(axis, float(p.get("max_level_offset", 0.0)))
    phase = float(p.get("phase", 0.0))
    duty = float(p.get("duty_cycle", 0.5))
    mode = str(p.get("mode", "additive"))
    fade_in = int(p.get("ramp_in_ms", 0)) / 1000.0
    fade_out = int(p.get("ramp_out_ms", 0)) / 1000.0

    # offset (center of oscillation relative to baseline) in normalized units
    offset_norm = mlo_norm - amp_norm

    blend = BlendMode.ADDITIVE if mode == "additive" else BlendMode.OVERRIDE
    layer_center = 50

    if blend == BlendMode.ADDITIVE:
        # WaveformSnippet center encodes additive offset from layer_center=50
        snip_center = int(round(50 + offset_norm * 100))
    else:
        # OVERRIDE: absolute pos values; center at offset_norm*100
        snip_center = int(round(offset_norm * 100))

    amplitude_pos = amp_norm * 100.0

    snip = WaveformSnippet(
        waveform=waveform,
        frequency=freq,
        amplitude=amplitude_pos,
        center=snip_center,
        phase=phase,
        duty_cycle=duty,
        resolution_hz=100.0,
    )
    actions = snip.generate(span)

    layer_name = f"event:{axis}:{waveform}" + (f":{group}" if group else "")
    return Layer(
        actions=actions,
        name=layer_name,
        blend=blend,
        span=span,
        fade_in=fade_in,
        fade_out=fade_out,
        center=layer_center,
    )


def _translate_linear_change(
    step: Step, axis: str, span: tuple[float, float], lib: EventLibrary, group: str | None
) -> Layer:
    p = step.params
    norm = lib.normalization

    start_raw = float(p.get("start_value", 0.0))
    end_raw = float(p.get("end_value", start_raw))
    mode = str(p.get("mode", "additive"))
    fade_in = int(p.get("ramp_in_ms", 0)) / 1000.0
    fade_out = int(p.get("ramp_out_ms", 0)) / 1000.0

    start_norm = norm.normalize(axis, start_raw)
    end_norm = norm.normalize(axis, end_raw)

    blend = BlendMode.ADDITIVE if mode == "additive" else BlendMode.OVERRIDE
    layer_center = 50

    if blend == BlendMode.ADDITIVE:
        start_pos = int(round(max(0, min(100, 50 + start_norm * 100))))
        end_pos = int(round(max(0, min(100, 50 + end_norm * 100))))
    else:
        start_pos = int(round(max(0, min(100, start_norm * 100))))
        end_pos = int(round(max(0, min(100, end_norm * 100))))

    t_start, t_end = span
    actions = ActionList()
    actions.add(Action(t_start, start_pos))
    actions.add(Action(t_end, end_pos))

    layer_name = f"event:{axis}:linear" + (f":{group}" if group else "")
    return Layer(
        actions=actions,
        name=layer_name,
        blend=blend,
        span=span,
        fade_in=fade_in,
        fade_out=fade_out,
        center=layer_center,
    )


# Registry: op type -> translator function
_TRANSLATORS: dict[str, Callable] = {
    "apply_modulation": _translate_modulation,
    "apply_linear_change": _translate_linear_change,
}

# ------------------------------------------------------------------ public API


def translate_event(
    event: EventDefinition,
    lib: EventLibrary,
    start_ms: float,
    *,
    param_overrides: dict | None = None,
    group: str | None = None,
) -> list[tuple[str, Layer]]:
    """Translate an event into (channel_name, Layer) pairs.

    Returns one pair per (step × axis) that has a known translator.
    The caller inserts the layers into matching channels.

    Args:
        event: The EventDefinition to apply.
        lib: EventLibrary supplying normalization config.
        start_ms: Event start time in milliseconds.
        param_overrides: Optional per-event param overrides (not yet wired to UI).
        group: Optional group tag appended to layer names for later batch removal.
    """
    overrides = param_overrides or {}
    insertions: list[tuple[str, Layer]] = []

    for step in event.steps:
        if not step.axes:
            continue
        translator = _TRANSLATORS.get(step.operation)
        if translator is None:
            warnings.warn(
                f"Unknown event operation {step.operation!r} — skipped",
                stacklevel=2,
            )
            continue

        step_start_s = (start_ms + step.start_offset_ms) / 1000.0
        # Merge param overrides with step params (overrides win)
        effective_params = dict(step.params)
        effective_params.update(overrides)
        effective_step = Step(
            operation=step.operation,
            axes=step.axes,
            start_offset_ms=step.start_offset_ms,
            params=effective_params,
        )

        duration_ms = int(effective_params.get("duration_ms", 5000))
        step_end_s = step_start_s + duration_ms / 1000.0
        span = (step_start_s, step_end_s)

        for axis in step.axes:
            try:
                layer = translator(effective_step, axis, span, lib, group)
                insertions.append((axis, layer))
            except Exception as exc:
                log.warning(
                    "Failed to translate step %r on axis %r: %s",
                    step.operation, axis, exc,
                )

    return insertions
