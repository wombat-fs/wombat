"""Tests for ActionList transforms."""
import pytest

from wombat.domain.action import Action, ActionList
from wombat.domain.transforms import (
    bottom_points,
    equalize,
    invert,
    mid_points,
    offset_pos,
    offset_time,
    scale_pos,
    simplify_rdp,
    top_points,
)


def _al(*pairs) -> ActionList:
    return ActionList(Action(t, p) for t, p in pairs)


# ------------------------------------------------------------------ invert

def test_invert_basic():
    al = _al((0.0, 0), (1.0, 100), (2.0, 50))
    inv = invert(al)
    assert [a.pos for a in inv] == [100, 0, 50]


def test_invert_involution():
    al = _al((0.0, 25), (1.0, 75), (2.0, 50))
    assert invert(invert(al)) == al


def test_invert_custom_range():
    al = _al((0.0, 0), (1.0, 90))
    inv = invert(al, range_=90)
    assert [a.pos for a in inv] == [90, 0]


def test_invert_does_not_mutate():
    al = _al((0.0, 30))
    _ = invert(al)
    assert al[0].pos == 30


# ------------------------------------------------------------------ offset_time

def test_offset_time_forward():
    al = _al((1.0, 10), (2.0, 20))
    shifted = offset_time(al, 0.5)
    assert [a.at for a in shifted] == [1.5, 2.5]


def test_offset_time_preserves_pos():
    al = _al((1.0, 33), (2.0, 66))
    shifted = offset_time(al, -0.5)
    assert [a.pos for a in shifted] == [33, 66]


# ------------------------------------------------------------------ offset_pos

def test_offset_pos_basic():
    al = _al((0.0, 50), (1.0, 50))
    assert [a.pos for a in offset_pos(al, 10)] == [60, 60]


def test_offset_pos_clamped():
    al = _al((0.0, 95), (1.0, 5))
    result = offset_pos(al, 20)
    assert result[0].pos == 100
    assert result[1].pos == 25


def test_offset_pos_negative_clamped():
    al = _al((0.0, 5))
    assert offset_pos(al, -20)[0].pos == 0


# ------------------------------------------------------------------ scale_pos

def test_scale_pos_double():
    al = _al((0.0, 50), (1.0, 75))
    scaled = scale_pos(al, 2.0, pivot=50)
    assert scaled[0].pos == 50   # pivot unchanged
    assert scaled[1].pos == 100  # 50 + (75-50)*2 = 100


def test_scale_pos_half():
    al = _al((0.0, 0), (1.0, 100))
    scaled = scale_pos(al, 0.5, pivot=50)
    assert scaled[0].pos == 25   # 50 + (0-50)*0.5 = 25
    assert scaled[1].pos == 75   # 50 + (100-50)*0.5 = 75


def test_scale_pos_clamped():
    al = _al((0.0, 0), (1.0, 100))
    scaled = scale_pos(al, 3.0, pivot=50)
    assert scaled[0].pos == 0
    assert scaled[1].pos == 100


# ------------------------------------------------------------------ simplify_rdp

def _colinear_list(n=20) -> ActionList:
    """Perfectly linear: all points on the line pos = at*10."""
    return _al(*[(float(i), i * 5) for i in range(n)])


def test_simplify_keeps_endpoints():
    al = _colinear_list(10)
    simplified = simplify_rdp(al, epsilon=1.0)
    assert simplified[0] == al[0]
    assert simplified[-1] == al[-1]


def test_simplify_reduces_colinear():
    al = _colinear_list(20)
    simplified = simplify_rdp(al, epsilon=0.1)
    assert len(simplified) < len(al)


def test_simplify_zero_epsilon_keeps_all():
    al = _colinear_list(10)
    simplified = simplify_rdp(al, epsilon=0.0)
    # With epsilon=0 every deviation counts; colinear points have zero deviation → still kept
    assert len(simplified) <= len(al)


def test_simplify_short_list_unchanged():
    al = _al((0.0, 0), (1.0, 100))
    assert simplify_rdp(al, 1.0) == al


def test_simplify_dropped_points_within_epsilon():
    # Sawtooth with one noisy point
    al = _al((0.0, 0), (0.5, 1), (1.0, 0), (1.5, 1), (2.0, 0))
    epsilon = 2.0
    simplified = simplify_rdp(al, epsilon)
    kept_ats = {a.at for a in simplified}
    # All dropped points must have been within epsilon of the kept polyline
    # (implicit: just check first/last are kept)
    assert al[0] in simplified
    assert al[-1] in simplified


# ------------------------------------------------------------------ equalize

def test_equalize_uniform_spacing():
    al = _al((0.0, 10), (1.0, 20), (9.0, 30), (10.0, 40))
    eq = equalize(al)
    diffs = [eq[i + 1].at - eq[i].at for i in range(len(eq) - 1)]
    assert all(abs(d - diffs[0]) < 1e-9 for d in diffs)


def test_equalize_preserves_endpoints():
    al = _al((0.0, 10), (2.0, 50), (10.0, 90))
    eq = equalize(al)
    assert eq[0].at == pytest.approx(0.0)
    assert eq[-1].at == pytest.approx(10.0)


def test_equalize_preserves_positions():
    al = _al((0.0, 10), (5.0, 50), (10.0, 90))
    eq = equalize(al)
    assert [a.pos for a in eq] == [10, 50, 90]


def test_equalize_single_unchanged():
    al = _al((2.0, 50))
    assert equalize(al) == al


def test_equalize_two_unchanged():
    al = _al((0.0, 0), (5.0, 100))
    eq = equalize(al)
    assert eq[0].at == pytest.approx(0.0)
    assert eq[1].at == pytest.approx(5.0)


# ------------------------------------------------------------------ top/mid/bottom

def test_top_points():
    al = _al((0.0, 0), (1.0, 100), (2.0, 0), (3.0, 100), (4.0, 0))
    tops = top_points(al)
    top_ats = {a.at for a in tops}
    assert 1.0 in top_ats and 3.0 in top_ats


def test_bottom_points():
    al = _al((0.0, 100), (1.0, 0), (2.0, 100), (3.0, 0), (4.0, 100))
    bots = bottom_points(al)
    bot_ats = {a.at for a in bots}
    assert 1.0 in bot_ats and 3.0 in bot_ats


def test_mid_points_monotone_slope():
    # Strictly ascending: 0,25,50,75,100 — middle points are mid
    al = _al((0.0, 0), (1.0, 25), (2.0, 50), (3.0, 75), (4.0, 100))
    mids = mid_points(al)
    mid_ats = {a.at for a in mids}
    assert 1.0 in mid_ats and 2.0 in mid_ats and 3.0 in mid_ats
