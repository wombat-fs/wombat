"""Parse funscript-tools event_definitions.yml into an EventLibrary.

Handles:
- `normalization` block → NormalizationConfig
- `groups` block → list[EventGroup]
- `definitions` block → dict[str, EventDefinition]
  - `default_params` dict
  - `steps` list: each step has operation, axis (comma-separated), optional
    start_offset, and params with $variable references resolved from default_params

No Qt, no mpv imports.
"""
from __future__ import annotations

import logging
import re

import yaml  # type: ignore[import-untyped]

from wombat.domain.events.model import (
    EventDefinition,
    EventGroup,
    EventLibrary,
    NormalizationConfig,
    Step,
)

log = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def _resolve(value: object, params: dict) -> object:
    """Recursively resolve $variable references from params into a value."""
    if isinstance(value, str):
        # Simple whole-string substitution: "$name" → value
        m = re.fullmatch(r"\$([A-Za-z_][A-Za-z0-9_]*)", value.strip())
        if m:
            resolved = params.get(m.group(1), value)
            return resolved
        # Partial substitution: "prefix_$name" → not needed yet, pass through
        return value
    if isinstance(value, dict):
        return {k: _resolve(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, params) for v in value]
    return value


def _resolve_params(raw_params: dict, default_params: dict) -> dict:
    """Return a flat dict of params with $var references replaced by their values."""
    # Merge: step params override default_params for resolution context
    context = dict(default_params)
    resolved: dict = {}
    for k, v in raw_params.items():
        resolved[k] = _resolve(v, context)
    return resolved


def _parse_step(raw: dict, default_params: dict) -> Step:
    operation = raw.get("operation", "")
    axis_str = str(raw.get("axis", ""))
    axes = [a.strip() for a in axis_str.split(",") if a.strip()]
    start_offset_ms = int(raw.get("start_offset", 0))
    raw_params = dict(raw.get("params", {}))
    params = _resolve_params(raw_params, default_params)
    # Ensure numeric types are coerced where expected
    for key in ("duration_ms", "ramp_in_ms", "ramp_out_ms", "start_offset"):
        if key in params:
            try:
                params[key] = int(params[key])
            except (TypeError, ValueError):
                pass
    for key in ("frequency", "amplitude", "max_level_offset", "phase",
                "duty_cycle", "start_value", "end_value"):
        if key in params:
            try:
                params[key] = float(params[key])
            except (TypeError, ValueError):
                pass
    return Step(operation=operation, axes=axes, start_offset_ms=start_offset_ms, params=params)


def _parse_event(name: str, raw: dict) -> EventDefinition:
    default_params = dict(raw.get("default_params", {}))
    steps_raw = raw.get("steps", [])
    steps = [_parse_step(s, default_params) for s in steps_raw]
    return EventDefinition(name=name, default_params=default_params, steps=steps)


def load_event_library(path: str) -> EventLibrary:
    """Parse a funscript-tools event_definitions.yml file into an EventLibrary."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Normalization
    norm_raw = data.get("normalization", {})
    axes: dict[str, tuple[float, str]] = {}
    for axis_name, cfg in norm_raw.items():
        max_val = float(cfg.get("max", 1.0))
        unit = str(cfg.get("unit", ""))
        axes[axis_name] = (max_val, unit)
    normalization = NormalizationConfig(axes=axes)

    # Groups
    groups: list[EventGroup] = []
    for g in data.get("groups", []):
        groups.append(EventGroup(
            name=str(g.get("name", "")),
            prefix=str(g.get("prefix", "")),
            description=str(g.get("description", "")),
        ))

    # Definitions
    definitions_raw = data.get("definitions", {})
    events: dict[str, EventDefinition] = {}
    for name, raw_def in definitions_raw.items():
        try:
            events[name] = _parse_event(name, raw_def)
        except Exception as exc:
            log.warning("Failed to parse event %r: %s", name, exc)

    return EventLibrary(normalization=normalization, events=events, groups=groups)
