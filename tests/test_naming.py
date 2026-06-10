"""Tests for wombat.app.naming — multi-axis filename convention."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from wombat.app.naming import (
    MAIN_CHANNEL_NAMES,
    channel_filename,
    discover_siblings,
    parse_channel_name,
)

# ------------------------------------------------------------------ channel_filename

def test_main_channel_names_produce_no_suffix():
    for name in MAIN_CHANNEL_NAMES:
        assert channel_filename("clip", name) == "clip.funscript"


def test_regular_channel_gets_suffix():
    assert channel_filename("clip", "alpha") == "clip.alpha.funscript"
    assert channel_filename("clip", "volume") == "clip.volume.funscript"
    assert channel_filename("clip", "pulse-width") == "clip.pulse-width.funscript"


def test_channel_filename_base_with_dots():
    assert channel_filename("my.video", "alpha") == "my.video.alpha.funscript"


# ------------------------------------------------------------------ parse_channel_name

def test_parse_main_channel():
    assert parse_channel_name("clip.funscript", "clip") == ""


def test_parse_regular_channel():
    assert parse_channel_name("clip.alpha.funscript", "clip") == "alpha"
    assert parse_channel_name("clip.volume.funscript", "clip") == "volume"
    assert parse_channel_name("clip.pulse-width.funscript", "clip") == "pulse-width"


def test_parse_wrong_base_returns_none():
    assert parse_channel_name("other.funscript", "clip") is None
    assert parse_channel_name("clip.funscript", "other") is None


def test_parse_non_funscript_returns_none():
    assert parse_channel_name("clip.mp4", "clip") is None
    assert parse_channel_name("clip.alpha.json", "clip") is None


def test_parse_double_dot_middle_returns_none():
    # "clip.alpha.beta.funscript" has two dots in the middle — not a valid single suffix
    assert parse_channel_name("clip.alpha.beta.funscript", "clip") is None


# ------------------------------------------------------------------ roundtrip

@pytest.mark.parametrize(
    "name", ["alpha", "beta", "volume", "frequency", "pulse-width", "pulse-rise"]
)
def test_roundtrip(name: str) -> None:
    fn = channel_filename("clip", name)
    assert parse_channel_name(fn, "clip") == name


def test_roundtrip_main():
    for name in MAIN_CHANNEL_NAMES:
        fn = channel_filename("clip", name)
        parsed = parse_channel_name(fn, "clip")
        assert parsed == ""  # all main names resolve back to "" (no suffix)


# ------------------------------------------------------------------ discover_siblings

def test_discover_siblings_finds_funscripts():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "clip.mp4").touch()
        (Path(d) / "clip.funscript").write_text('{"actions":[]}', encoding="utf-8")
        (Path(d) / "clip.alpha.funscript").write_text('{"actions":[]}', encoding="utf-8")
        (Path(d) / "clip.beta.funscript").write_text('{"actions":[]}', encoding="utf-8")
        # non-sibling
        (Path(d) / "other.funscript").write_text('{"actions":[]}', encoding="utf-8")

        siblings = discover_siblings(str(Path(d) / "clip.mp4"))
        names = [s[0] for s in siblings]
        assert "" in names
        assert "alpha" in names
        assert "beta" in names
        assert len(siblings) == 3


def test_discover_siblings_empty_directory():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "clip.mp4").touch()
        siblings = discover_siblings(str(Path(d) / "clip.mp4"))
        assert siblings == []


def test_discover_siblings_returns_absolute_paths():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "clip.mp4").touch()
        (Path(d) / "clip.funscript").write_text('{"actions":[]}', encoding="utf-8")
        siblings = discover_siblings(str(Path(d) / "clip.mp4"))
        assert len(siblings) == 1
        assert Path(siblings[0][1]).is_absolute()


def test_discover_siblings_sorted():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "clip.mp4").touch()
        (Path(d) / "clip.volume.funscript").write_text('{"actions":[]}', encoding="utf-8")
        (Path(d) / "clip.alpha.funscript").write_text('{"actions":[]}', encoding="utf-8")
        siblings = discover_siblings(str(Path(d) / "clip.mp4"))
        names = [s[0] for s in siblings]
        assert names == sorted(names)
