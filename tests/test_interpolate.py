"""Tests for linear interpolation."""
import numpy as np
import pytest

from wombat.domain.action import Action, ActionList
from wombat.domain.interpolate import value_at, values_at


def _al(*pairs) -> ActionList:
    return ActionList(Action(t, p) for t, p in pairs)


# ------------------------------------------------------------------ value_at

def test_empty_returns_zero():
    assert value_at(ActionList(), 1.0) == 0.0


def test_single_action_any_time():
    al = _al((2.0, 75))
    assert value_at(al, 0.0) == 75.0
    assert value_at(al, 2.0) == 75.0
    assert value_at(al, 99.0) == 75.0


def test_exact_endpoints():
    al = _al((0.0, 0), (1.0, 100))
    assert value_at(al, 0.0) == pytest.approx(0.0)
    assert value_at(al, 1.0) == pytest.approx(100.0)


def test_midpoint():
    al = _al((0.0, 0), (1.0, 100))
    assert value_at(al, 0.5) == pytest.approx(50.0)


def test_clamp_before_first():
    al = _al((1.0, 30), (2.0, 80))
    assert value_at(al, 0.0) == pytest.approx(30.0)


def test_clamp_after_last():
    al = _al((1.0, 30), (2.0, 80))
    assert value_at(al, 5.0) == pytest.approx(80.0)


def test_interpolation_quarter():
    al = _al((0.0, 0), (4.0, 100))
    assert value_at(al, 1.0) == pytest.approx(25.0)


def test_interpolation_multi_segment():
    al = _al((0.0, 0), (1.0, 100), (2.0, 0))
    assert value_at(al, 0.5) == pytest.approx(50.0)
    assert value_at(al, 1.5) == pytest.approx(50.0)


# ------------------------------------------------------------------ values_at

def test_values_at_matches_value_at():
    al = _al((0.0, 0), (1.0, 100), (2.0, 50))
    times = np.linspace(0.0, 2.0, 21)
    vec = values_at(al, times)
    for t, v in zip(times, vec):
        assert v == pytest.approx(value_at(al, float(t)), abs=1e-9)


def test_values_at_empty():
    result = values_at(ActionList(), np.array([0.0, 1.0]))
    np.testing.assert_array_equal(result, [0.0, 0.0])


def test_values_at_dtype():
    al = _al((0.0, 0), (1.0, 100))
    result = values_at(al, np.array([0.5]))
    assert result.dtype == np.float64
