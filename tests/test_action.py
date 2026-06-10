"""Tests for Action and ActionList."""
import pytest
import numpy as np

from wombat.domain.action import Action, ActionList


# ------------------------------------------------------------------ Action

def test_action_pos_clamped():
    assert Action(1.0, 150).pos == 100
    assert Action(1.0, -10).pos == 0


def test_action_frozen():
    a = Action(1.0, 50)
    with pytest.raises((AttributeError, TypeError)):
        a.pos = 99  # type: ignore[misc]


def test_action_hashable():
    s = {Action(1.0, 50), Action(1.0, 50), Action(2.0, 50)}
    assert len(s) == 2


# ------------------------------------------------------------------ ActionList basics

def test_empty_list():
    al = ActionList()
    assert len(al) == 0
    assert list(al) == []


def test_sorted_on_construction():
    al = ActionList([Action(3.0, 10), Action(1.0, 20), Action(2.0, 30)])
    assert [a.at for a in al] == [1.0, 2.0, 3.0]


def test_dedup_on_construction_last_wins():
    # Same at twice — last one in iteration order wins
    al = ActionList([Action(1.0, 10), Action(1.0, 99)])
    assert len(al) == 1
    assert al[0].pos == 99


def test_add_replaces_same_at():
    al = ActionList([Action(1.0, 10)])
    al.add(Action(1.0, 75))
    assert len(al) == 1
    assert al[0].pos == 75


def test_add_inserts_sorted():
    al = ActionList([Action(1.0, 0), Action(3.0, 100)])
    al.add(Action(2.0, 50))
    assert [a.at for a in al] == [1.0, 2.0, 3.0]


def test_remove_by_action():
    a = Action(1.0, 50)
    al = ActionList([a, Action(2.0, 100)])
    al.remove(a)
    assert len(al) == 1
    assert al[0].at == 2.0


def test_remove_raises_if_absent():
    al = ActionList([Action(1.0, 50)])
    with pytest.raises(ValueError):
        al.remove(Action(2.0, 50))


def test_remove_at():
    al = ActionList([Action(1.0, 10), Action(2.0, 20)])
    al.remove_at(1.0)
    assert len(al) == 1 and al[0].at == 2.0


def test_remove_at_raises_if_absent():
    al = ActionList([Action(1.0, 50)])
    with pytest.raises(ValueError):
        al.remove_at(9.9)


def test_equality():
    al1 = ActionList([Action(1.0, 10), Action(2.0, 20)])
    al2 = ActionList([Action(1.0, 10), Action(2.0, 20)])
    al3 = ActionList([Action(1.0, 10)])
    assert al1 == al2
    assert al1 != al3


# ------------------------------------------------------------------ lookups

def test_at_time_exact():
    al = ActionList([Action(1.0, 10), Action(2.0, 20)])
    assert al.at_time(1.0, 0.001) == Action(1.0, 10)


def test_at_time_within_error():
    al = ActionList([Action(1.0, 10), Action(2.0, 20)])
    assert al.at_time(1.009, 0.01) == Action(1.0, 10)


def test_at_time_outside_error():
    al = ActionList([Action(1.0, 10), Action(2.0, 20)])
    assert al.at_time(1.1, 0.01) is None


def test_at_time_picks_nearest():
    al = ActionList([Action(1.0, 10), Action(1.05, 20)])
    # t=1.03 is closer to 1.05 (dist 0.02) than to 1.0 (dist 0.03) — wait, 1.03-1.0=0.03, 1.05-1.03=0.02
    result = al.at_time(1.03, 0.05)
    assert result == Action(1.05, 20)


def test_closest_middle():
    al = ActionList([Action(1.0, 0), Action(3.0, 100)])
    assert al.closest(2.0) == Action(1.0, 0)  # equidistant → prefer earlier
    assert al.closest(2.1) == Action(3.0, 100)


def test_closest_empty():
    assert ActionList().closest(1.0) is None


def test_next_after():
    al = ActionList([Action(1.0, 0), Action(2.0, 50), Action(3.0, 100)])
    assert al.next_after(1.0) == Action(2.0, 50)
    assert al.next_after(3.0) is None


def test_before():
    al = ActionList([Action(1.0, 0), Action(2.0, 50), Action(3.0, 100)])
    assert al.before(3.0) == Action(2.0, 50)
    assert al.before(1.0) is None


def test_index_range_basic():
    al = ActionList([Action(float(i), i * 10) for i in range(10)])
    lo, hi = al.index_range(2.0, 5.0)
    assert al[lo].at == 2.0
    assert al[hi - 1].at == 5.0


def test_index_range_empty_window():
    al = ActionList([Action(1.0, 0), Action(5.0, 100)])
    lo, hi = al.index_range(2.0, 4.0)
    assert lo == hi  # no actions in window


# ------------------------------------------------------------------ numpy

def test_to_arrays_empty():
    at, pos = ActionList().to_arrays()
    assert len(at) == 0 and len(pos) == 0


def test_to_arrays():
    al = ActionList([Action(0.1, 0), Action(0.5, 100)])
    at, pos = al.to_arrays()
    assert at.dtype == np.float64
    assert pos.dtype == np.int32
    np.testing.assert_array_equal(at, [0.1, 0.5])
    np.testing.assert_array_equal(pos, [0, 100])


def test_from_arrays_round_trip():
    al = ActionList([Action(float(i) * 0.1, i * 10) for i in range(5)])
    at, pos = al.to_arrays()
    al2 = ActionList.from_arrays(at, pos)
    assert al == al2


def test_copy_is_independent():
    al = ActionList([Action(1.0, 50)])
    al2 = al.copy()
    al.add(Action(2.0, 75))
    assert len(al2) == 1
