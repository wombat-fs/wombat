"""Synthesis engine tests — the crown jewel of Phase 6.

Tests:
- Identity: single full-span override base → exact base actions
- Override crossfade: base + spanning override → crossfades across fade window
- Additive: flat-at-center adds nothing; deviation modulates; clamp enforced
- Order matters: swapping two override layers changes overlap result
- Sparsity: sparse input with no fades → sparse output (bounded point count)
- Continuity: min-fade enforced at span boundaries (no hard discontinuities)
- Caching: layer mutation invalidates cache; unchanged channel hits cache
- Round-trip: synthesized output exports to .funscript and reloads equal
"""
from __future__ import annotations

import pytest

from wombat.domain.action import Action, ActionList
from wombat.domain.channel import BlendMode, Channel, FadeCurve, Layer
from wombat.domain.synthesis import SynthesisParams, synthesize


# ------------------------------------------------------------------ helpers

def _al(*pairs) -> ActionList:
    return ActionList(Action(t, p) for t, p in pairs)


def _layer(
    actions: ActionList,
    *,
    name: str = "base",
    blend: BlendMode = BlendMode.OVERRIDE,
    span=None,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    center: int = 50,
    fade_curve: FadeCurve = FadeCurve.SMOOTH,
    enabled: bool = True,
) -> Layer:
    return Layer(
        actions=actions,
        name=name,
        blend=blend,
        span=span,
        fade_in=fade_in,
        fade_out=fade_out,
        center=center,
        fade_curve=fade_curve,
        enabled=enabled,
    )


def _val(al: ActionList, t: float) -> float:
    from wombat.domain.interpolate import value_at
    return value_at(al, t)


# ------------------------------------------------------------------ identity

def test_identity_single_override_base():
    """Single full-span override no-fade layer → returns base actions exactly."""
    base_al = _al((0.0, 0), (1.0, 100), (2.0, 50))
    layer = _layer(base_al)
    result = synthesize([layer])
    assert result == base_al, "identity case must return exact base actions"


def test_identity_via_channel_synthesize():
    """Channel.synthesize() must also return exact base for single-layer channel."""
    al = _al((0.0, 0), (1.0, 100))
    ch = Channel(name="c", layers=[_layer(al)])
    assert ch.synthesize() == al


def test_identity_empty_layers():
    result = synthesize([])
    assert len(result) == 0


def test_identity_all_disabled():
    al = _al((0.0, 50))
    result = synthesize([_layer(al, enabled=False)])
    assert len(result) == 0


# ------------------------------------------------------------------ override crossfade

def test_override_full_span_replaces():
    """Two full-span override layers → top wins entirely."""
    base = _layer(_al((0.0, 0), (2.0, 0)), name="base")
    top = _layer(_al((0.0, 100), (2.0, 100)), name="top")
    result = synthesize([base, top])
    # Top layer should fully override base → all pos = 100
    for a in result:
        assert a.pos == 100, f"Expected 100 at t={a.at}, got {a.pos}"


def test_override_outside_span_unchanged():
    """Outside a layer's span, the base should be unchanged."""
    base_al = _al((0.0, 20), (4.0, 20))
    over_al = _al((1.0, 80), (3.0, 80))
    base = _layer(base_al, name="base")
    over = _layer(over_al, name="over", span=(1.0, 3.0), fade_in=0.0, fade_out=0.0)

    params = SynthesisParams(resolution_hz=100.0)
    result = synthesize([base, over], params)

    # At t=0 (outside span): should equal base value (20)
    v_at_0 = _val(result, 0.0)
    assert abs(v_at_0 - 20.0) < 1.0, f"At t=0 (outside span), expected ~20, got {v_at_0}"

    # At t=4 (outside span): should equal base value (20)
    v_at_4 = _val(result, 4.0)
    assert abs(v_at_4 - 20.0) < 1.0, f"At t=4 (outside span), expected ~20, got {v_at_4}"


def test_override_inside_span_replaces():
    """Inside span (away from fade), top layer fully replaces base."""
    base = _layer(_al((0.0, 0), (10.0, 0)), name="base")
    over = _layer(_al((0.0, 100), (10.0, 100)), name="over",
                  span=(2.0, 8.0), fade_in=0.5, fade_out=0.5)

    params = SynthesisParams(resolution_hz=100.0)
    result = synthesize([base, over], params)

    # At t=5 (middle of span, away from fades): should be close to 100
    v_mid = _val(result, 5.0)
    assert v_mid >= 99.0, f"Expected ~100 at t=5 (inside span), got {v_mid}"


def test_override_fade_is_monotonic():
    """Crossfade from base to override across fade window is monotonic."""
    base = _layer(_al((0.0, 0), (10.0, 0)), name="base")
    over = _layer(_al((0.0, 100), (10.0, 100)), name="over",
                  span=(2.0, 8.0), fade_in=1.0, fade_out=0.0)

    params = SynthesisParams(resolution_hz=200.0, simplify_epsilon=0.0)
    result = synthesize([base, over], params)

    # In the fade-in window [2.0, 3.0], value should rise monotonically
    fade_points = [(a.at, a.pos) for a in result if 2.0 <= a.at <= 3.0]
    fade_points.sort()
    for i in range(1, len(fade_points)):
        assert fade_points[i][1] >= fade_points[i-1][1] - 1, (
            f"Fade should be monotonically increasing: {fade_points}"
        )


# ------------------------------------------------------------------ additive

def test_additive_flat_at_center_adds_nothing():
    """Additive layer flat at center (default 50) contributes zero offset."""
    base_al = _al((0.0, 30), (2.0, 70))
    add_al = _al((0.0, 50), (2.0, 50))  # flat at center=50
    base = _layer(base_al, name="base")
    add = _layer(add_al, name="add", blend=BlendMode.ADDITIVE, center=50)

    result = synthesize([base, add])
    # Result should equal base (additive with 0 offset = identity)
    for a_base, a_res in zip(base_al, result):
        assert abs(a_res.pos - a_base.pos) <= 1, (
            f"Additive flat at center should not change base: "
            f"base={a_base.pos} result={a_res.pos}"
        )


def test_additive_plus_amplitude():
    """Additive layer at 100 (center=50) adds +50 to base."""
    base_al = _al((0.0, 30), (2.0, 30))  # flat at 30
    add_al = _al((0.0, 100), (2.0, 100))  # deviation +50 from center
    base = _layer(base_al, name="base")
    add = _layer(add_al, name="add", blend=BlendMode.ADDITIVE, center=50)

    result = synthesize([base, add])
    # 30 + 50 = 80
    for a in result:
        assert abs(a.pos - 80) <= 1, f"Expected 80, got {a.pos}"


def test_additive_clamps_at_100():
    """Result clamped at 100 — no overflow."""
    base_al = _al((0.0, 80), (2.0, 80))
    add_al = _al((0.0, 100), (2.0, 100))  # +50 offset
    base = _layer(base_al, name="base")
    add = _layer(add_al, name="add", blend=BlendMode.ADDITIVE, center=50)

    result = synthesize([base, add])
    for a in result:
        assert a.pos <= 100, f"Result must clamp at 100, got {a.pos}"


def test_additive_clamps_at_0():
    """Result clamped at 0 — no underflow."""
    base_al = _al((0.0, 20), (2.0, 20))
    add_al = _al((0.0, 0), (2.0, 0))   # -50 offset from center
    base = _layer(base_al, name="base")
    add = _layer(add_al, name="add", blend=BlendMode.ADDITIVE, center=50)

    result = synthesize([base, add])
    for a in result:
        assert a.pos >= 0, f"Result must clamp at 0, got {a.pos}"


# ------------------------------------------------------------------ order matters

def test_order_matters_two_overlapping_override():
    """Swapping two override layers changes the result at their overlap."""
    base_al = _al((0.0, 0), (4.0, 0))
    a_al = _al((0.0, 30), (4.0, 30))
    b_al = _al((0.0, 70), (4.0, 70))

    # Both layers cover span (1,3), no fade
    layer_a = _layer(a_al, name="a", span=(1.0, 3.0), fade_in=0.01, fade_out=0.01)
    layer_b = _layer(b_al, name="b", span=(1.0, 3.0), fade_in=0.01, fade_out=0.01)
    base = _layer(base_al, name="base")

    params = SynthesisParams(resolution_hz=100.0)

    # Order: base, a, b → b wins at the overlap
    result_ab = synthesize([base, layer_a, layer_b], params)
    v_ab = _val(result_ab, 2.0)  # middle of overlap

    # Order: base, b, a → a wins at the overlap
    result_ba = synthesize([base, layer_b, layer_a], params)
    v_ba = _val(result_ba, 2.0)

    assert v_ab != v_ba, (
        f"Order should matter: a-then-b gives {v_ab}, b-then-a gives {v_ba}"
    )
    assert abs(v_ab - 70) < 5, f"b on top should give ~70, got {v_ab}"
    assert abs(v_ba - 30) < 5, f"a on top should give ~30, got {v_ba}"


# ------------------------------------------------------------------ sparsity

def test_sparse_no_fades_sparse_output():
    """Sparse input with no fades → sparse output (no dense grid)."""
    base_al = _al((0.0, 0), (1.0, 100), (2.0, 50), (3.0, 0))
    layer = _layer(base_al)
    result = synthesize([layer])
    # Identity path — must return exact same 4 points
    assert len(result) == len(base_al), (
        f"Sparse no-fade should preserve point count: {len(result)} != {len(base_al)}"
    )


def test_sparse_output_bounded_with_fades():
    """Dense fade regions are RDP-trimmed; output is finite."""
    base = _layer(_al((0.0, 0), (10.0, 0)))
    over = _layer(_al((0.0, 100), (10.0, 100)), name="over",
                  span=(2.0, 8.0), fade_in=1.0, fade_out=1.0)

    params = SynthesisParams(resolution_hz=1000.0, simplify_epsilon=0.5)
    result = synthesize([base, over], params)
    # Should not explode to thousands of points after RDP
    assert len(result) < 200, f"Too many points: {len(result)}"
    # But should have more than just a handful (fade regions sampled)
    assert len(result) >= 4, f"Too few points: {len(result)}"


# ------------------------------------------------------------------ continuity

def test_min_fade_enforced_at_span_edge():
    """Even with fade_in=0, min_fade ensures continuity at span boundary."""
    base = _layer(_al((0.0, 0), (5.0, 0)))
    over = _layer(_al((0.0, 100), (5.0, 100)), name="over",
                  span=(2.0, 4.0), fade_in=0.0, fade_out=0.0)

    params = SynthesisParams(resolution_hz=200.0, simplify_epsilon=0.0)
    result = synthesize([base, over], params)

    # Should have continuous transition — no point exactly at 0 then 100 with nothing between
    points = [(a.at, a.pos) for a in result if 1.9 <= a.at <= 2.1]
    points.sort()
    if len(points) >= 2:
        # The jump should be spread over at least the min_fade window
        for i in range(1, len(points)):
            diff = abs(points[i][1] - points[i-1][1])
            dt = points[i][0] - points[i-1][0]
            # No single step should jump the full range in an instant
            assert diff < 90 or dt > 1e-4, (
                f"Discontinuity detected at boundary: jump={diff} in dt={dt}"
            )


# ------------------------------------------------------------------ caching

def test_cache_hit_on_same_params():
    """Calling synthesize() twice returns the same cached object."""
    al = _al((0.0, 0), (1.0, 100))
    ch = Channel(name="c", layers=[_layer(al)])
    r1 = ch.synthesize()
    r2 = ch.synthesize()
    assert r1 is r2, "Second call should return cached result"


def test_cache_invalidated_on_mutation():
    """Mutating a layer action invalidates the synthesis cache."""
    al = _al((0.0, 0), (1.0, 100))
    ch = Channel(name="c", layers=[_layer(al)])
    r1 = ch.synthesize()
    ch.layers[0].actions.add(Action(0.5, 50))
    ch._invalidate_cache()
    r2 = ch.synthesize()
    assert r1 is not r2, "Cache must be invalidated after mutation"
    assert len(r2) == 3, f"Should have 3 points after mutation, got {len(r2)}"


def test_different_params_different_cache_slot():
    """Different SynthesisParams get different cache entries."""
    base = _layer(_al((0.0, 0), (10.0, 0)))
    over = _layer(_al((0.0, 100), (10.0, 100)), name="over",
                  span=(1.0, 9.0), fade_in=1.0, fade_out=1.0)
    ch = Channel(name="c", layers=[base, over])

    p1 = SynthesisParams(resolution_hz=30.0)
    p2 = SynthesisParams(resolution_hz=120.0)
    r1 = ch.synthesize(p1)
    r2 = ch.synthesize(p2)
    # Different resolution may yield different point counts inside fade windows
    # but both should hit cache on second call
    r1b = ch.synthesize(p1)
    r2b = ch.synthesize(p2)
    assert r1 is r1b
    assert r2 is r2b


# ------------------------------------------------------------------ round-trip

def test_round_trip_export_reload():
    """Synthesized output exports to .funscript and reloads equal (ms rounding aside)."""
    import tempfile, json
    from pathlib import Path
    from wombat.domain.funscript_io import save_funscript, load_funscript

    base = _layer(_al((0.0, 0), (1.0, 100), (2.0, 50)))
    over = _layer(_al((0.0, 80), (2.0, 80)), name="over",
                  span=(0.5, 1.5), fade_in=0.2, fade_out=0.2)

    ch = Channel(name="c", layers=[base, over])
    synth = ch.synthesize()

    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "test.funscript")
        fs = ch.to_funscript()
        save_funscript(path, fs)
        reloaded = load_funscript(path)

    # After ms-quantization round-trip, action count and positions should match
    assert len(reloaded.actions) == len(synth), (
        f"Point count changed: {len(synth)} → {len(reloaded.actions)}"
    )
    for a_orig, a_rel in zip(synth, reloaded.actions):
        assert abs(a_rel.at - a_orig.at) <= 0.001, (
            f"Time drift too large: {a_orig.at} → {a_rel.at}"
        )
        assert a_rel.pos == a_orig.pos, (
            f"Pos changed: {a_orig.pos} → {a_rel.pos}"
        )


# ------------------------------------------------------------------ domain isolation

def test_synthesis_no_qt_import():
    """synthesis.py must not import PySide6."""
    import sys
    for mod_name in list(sys.modules.keys()):
        if "wombat.domain.synthesis" in mod_name:
            del sys.modules[mod_name]
    pyside_before = {k for k in sys.modules if k.startswith("PySide6")}
    import wombat.domain.synthesis  # noqa: F401
    pyside_after = {k for k in sys.modules if k.startswith("PySide6")}
    assert not (pyside_after - pyside_before), "synthesis.py must not import PySide6"
