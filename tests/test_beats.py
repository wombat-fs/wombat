"""Tests for the BeatGrid data model, the .beats format, and detection."""
import os
import stat

import numpy as np
import pytest

from wombat.audio import beats as beats_mod
from wombat.audio.beats import (
    DOWNBEAT_COUNT,
    UNKNOWN_COUNT,
    BeatGrid,
    detect_beats,
    parse_beats,
    resolve_beat_tool,
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


# ---------------------------------------------------------------- tool resolution

def test_resolve_explicit_args_win(monkeypatch):
    # explicit args must short-circuit settings/env/which entirely
    monkeypatch.setattr(beats_mod, "_get_settings", lambda: None)
    monkeypatch.setenv("WOMBAT_BEAT_THIS_BIN", "/env/bin")
    monkeypatch.setenv("WOMBAT_BEAT_THIS_MODEL", "/env/model")
    b, m = resolve_beat_tool("/explicit/bin", "/explicit/model")
    assert (b, m) == ("/explicit/bin", "/explicit/model")


def test_resolve_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(beats_mod, "_get_settings", lambda: None)
    monkeypatch.setenv("WOMBAT_BEAT_THIS_BIN", "/env/bin")
    monkeypatch.setenv("WOMBAT_BEAT_THIS_MODEL", "/env/model")
    assert resolve_beat_tool() == ("/env/bin", "/env/model")


def test_resolve_missing_returns_none(monkeypatch):
    monkeypatch.setattr(beats_mod, "_get_settings", lambda: None)
    monkeypatch.delenv("WOMBAT_BEAT_THIS_BIN", raising=False)
    monkeypatch.delenv("WOMBAT_BEAT_THIS_MODEL", raising=False)
    monkeypatch.setattr(beats_mod.shutil, "which", lambda _: None)
    assert resolve_beat_tool() == (None, None)


# -------------------------------------------------------------------- detection

def _write_script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def fake_tools(tmp_path, monkeypatch):
    """Fake ffmpeg + beat binary; isolated cache dir; counts binary invocations."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(beats_mod, "_cache_dir", lambda: cache_dir)

    # fake ffmpeg: writes a non-empty "wav" to whichever arg ends in .wav
    ffmpeg = tmp_path / "ffmpeg"
    _write_script(
        ffmpeg,
        'for a in "$@"; do case "$a" in *.wav) printf "RIFFfake" > "$a";; esac; done\n',
    )
    monkeypatch.setattr(beats_mod, "ffmpeg_path", lambda: str(ffmpeg))

    # fake beat binary: writes fixed beats to the --output-beats target and
    # bumps a call counter so cache hits are observable.
    counter = tmp_path / "calls"
    binary = tmp_path / "beat_this_cpp"
    _write_script(
        binary,
        f'echo x >> "{counter}"\n'
        'prev=""; out=""\n'
        'for a in "$@"; do [ "$prev" = "--output-beats" ] && out="$a"; prev="$a"; done\n'
        'printf "0.500\\t1\\n1.000\\t2\\n1.500\\t3\\n" > "$out"\n',
    )
    model = tmp_path / "model.onnx"
    model.write_text("fake-model")

    video = tmp_path / "clip.mp4"
    video.write_text("fake-video")

    return {
        "binary": str(binary),
        "model": str(model),
        "video": str(video),
        "counter": counter,
    }


def test_detect_beats_end_to_end(fake_tools):
    grid = detect_beats(
        fake_tools["video"],
        binary=fake_tools["binary"],
        model=fake_tools["model"],
    )
    assert grid is not None
    assert list(grid.times) == pytest.approx([0.5, 1.0, 1.5])
    assert list(grid.counts) == [1, 2, 3]


def test_detect_beats_uses_cache(fake_tools):
    kw = dict(binary=fake_tools["binary"], model=fake_tools["model"])
    detect_beats(fake_tools["video"], **kw)
    detect_beats(fake_tools["video"], **kw)   # should hit cache, not re-run binary
    n_calls = len(fake_tools["counter"].read_text().splitlines())
    assert n_calls == 1


def test_detect_beats_cache_disabled_reruns(fake_tools):
    kw = dict(binary=fake_tools["binary"], model=fake_tools["model"])
    detect_beats(fake_tools["video"], use_cache=False, **kw)
    detect_beats(fake_tools["video"], use_cache=False, **kw)
    n_calls = len(fake_tools["counter"].read_text().splitlines())
    assert n_calls == 2


def test_detect_beats_missing_tool_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(beats_mod, "_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(beats_mod, "_get_settings", lambda: None)
    monkeypatch.delenv("WOMBAT_BEAT_THIS_BIN", raising=False)
    monkeypatch.delenv("WOMBAT_BEAT_THIS_MODEL", raising=False)
    monkeypatch.setattr(beats_mod.shutil, "which", lambda _: None)
    assert detect_beats(str(tmp_path / "clip.mp4")) is None


def test_detect_beats_binary_failure_returns_none(fake_tools, tmp_path):
    # a binary that exits non-zero must yield None, not raise
    failing = tmp_path / "failing"
    _write_script(failing, 'echo "boom" >&2\nexit 3\n')
    grid = detect_beats(
        fake_tools["video"],
        binary=str(failing),
        model=fake_tools["model"],
    )
    assert grid is None


# ---------------------------------------------------------- real-binary integration

@pytest.mark.skipif(
    not (os.environ.get("WOMBAT_BEAT_THIS_BIN") and resolve_beat_tool()[1]),
    reason="real beat_this_cpp binary/model not configured",
)
def test_detect_beats_real_binary_smoke():
    # Requires WOMBAT_BEAT_THIS_BIN + a resolvable model + a real media file.
    media = os.environ.get("WOMBAT_BEAT_TEST_MEDIA")
    if not media or not os.path.exists(media):
        pytest.skip("set WOMBAT_BEAT_TEST_MEDIA to a real audio/video file")
    grid = detect_beats(media, use_cache=False)
    assert grid is not None and len(grid) > 0
