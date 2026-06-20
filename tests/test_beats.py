"""Tests for the BeatGrid data model and the .beats file format."""
import numpy as np
import pytest

from wombat.audio.beats import (
    DOWNBEAT_COUNT,
    UNKNOWN_COUNT,
    BeatGrid,
    parse_beats,
    serialize_beats,
)


def _grid(*pairs) -> BeatGrid:
    times = [t for t, _ in pairs]
    counts = [c for _, c in pairs]
    return BeatGrid(np.asarray(times, dtype=np.float64),
                    np.asarray(counts, dtype=np.int32))


# --------------------------------------------------------------------- BeatGrid

def test_empty_grid():
    g = BeatGrid.empty()
    assert len(g) == 0
    assert g.nearest(1.0) is None
    assert len(g.downbeats) == 0
    assert len(g.in_span(0.0, 10.0)) == 0


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        BeatGrid(np.array([1.0, 2.0]), np.array([1], dtype=np.int32))


def test_construction_sorts_times_and_counts_together():
    g = _grid((2.0, 2), (1.0, 1), (3.0, 3))
    assert list(g.times) == [1.0, 2.0, 3.0]
    assert list(g.counts) == [1, 2, 3]


def test_dtypes_normalized():
    g = BeatGrid([1, 2, 3], [1, 2, 3])  # plain lists
    assert g.times.dtype == np.float64
    assert g.counts.dtype == np.int32


def test_downbeats():
    g = _grid((0.34, 1), (0.68, 2), (1.02, 3), (1.36, 4), (1.70, 1))
    assert list(g.downbeats) == pytest.approx([0.34, 1.70])


def test_in_span_inclusive():
    g = _grid((0.5, 1), (1.0, 2), (1.5, 3), (2.0, 4))
    sub = g.in_span(1.0, 1.5)
    assert list(sub.times) == [1.0, 1.5]
    assert list(sub.counts) == [2, 3]


def test_in_span_handles_reversed_bounds():
    g = _grid((0.5, 1), (1.0, 2), (1.5, 3))
    assert list(g.in_span(1.5, 0.5).times) == [0.5, 1.0, 1.5]


def test_nearest_picks_closest_either_side():
    g = _grid((1.0, 1), (2.0, 2), (3.0, 3))
    assert g.nearest(1.4) == 1.0
    assert g.nearest(1.6) == 2.0
    assert g.nearest(0.0) == 1.0    # before first
    assert g.nearest(9.0) == 3.0    # after last
    assert g.nearest(2.0) == 2.0    # exact


# ----------------------------------------------------------------- parse_beats

def test_parse_tab_separated():
    text = "0.340\t4\n0.681\t1\n1.023\t2\n"
    g = parse_beats(text)
    assert list(g.times) == pytest.approx([0.340, 0.681, 1.023])
    assert list(g.counts) == [4, 1, 2]


def test_parse_space_separated():
    g = parse_beats("0.5 1\n1.0 2\n")
    assert list(g.times) == pytest.approx([0.5, 1.0])
    assert list(g.counts) == [1, 2]


def test_parse_skips_blank_and_unparseable_lines():
    text = "\n# header\n0.5\t1\n\nnotanumber\n1.0\t2\n"
    g = parse_beats(text)
    assert list(g.times) == pytest.approx([0.5, 1.0])
    assert list(g.counts) == [1, 2]


def test_parse_single_column_defaults_to_unknown():
    g = parse_beats("0.5\n1.0\n")
    assert list(g.times) == pytest.approx([0.5, 1.0])
    assert list(g.counts) == [UNKNOWN_COUNT, UNKNOWN_COUNT]


def test_parse_empty_text():
    g = parse_beats("")
    assert len(g) == 0


# ------------------------------------------------------------- serialize_beats

def test_serialize_with_counts():
    g = _grid((0.34, 1), (0.681, 2))
    assert serialize_beats(g) == "0.340\t1\n0.681\t2\n"


def test_serialize_unknown_count_single_column():
    g = _grid((0.5, UNKNOWN_COUNT))
    assert serialize_beats(g) == "0.500\n"


def test_serialize_empty_has_no_trailing_newline():
    assert serialize_beats(BeatGrid.empty()) == ""


# --------------------------------------------------------------- round-tripping

def test_round_trip_preserves_grid():
    g = _grid((0.340, 4), (0.681, 1), (1.023, 2), (1.364, 3))
    g2 = parse_beats(serialize_beats(g))
    assert list(g2.times) == pytest.approx(list(g.times))
    assert list(g2.counts) == list(g.counts)


def test_round_trip_unknown_counts():
    g = _grid((0.5, UNKNOWN_COUNT), (1.0, UNKNOWN_COUNT))
    g2 = parse_beats(serialize_beats(g))
    assert list(g2.counts) == [UNKNOWN_COUNT, UNKNOWN_COUNT]


def test_downbeat_constant():
    assert DOWNBEAT_COUNT == 1
