"""Tests for funscript_io: load, save, round-trip, unknown-key preservation."""
import json
import tempfile
from pathlib import Path

import pytest

from wombat.domain.action import Action, ActionList
from wombat.domain.funscript import Funscript, FunscriptMetadata
from wombat.domain.funscript_io import FunscriptError, load_funscript, save_funscript

FIXTURES = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------------ load

def test_load_basic():
    fs = load_funscript(FIXTURES / "basic.funscript")
    assert len(fs.actions) == 10
    assert fs.version == "1.0"
    assert fs.inverted is False
    assert fs.range_ == 90


def test_load_first_last_actions():
    fs = load_funscript(FIXTURES / "basic.funscript")
    assert fs.actions[0] == Action(0.1, 0)
    assert fs.actions[-1] == Action(5.0, 50)


def test_load_metadata():
    fs = load_funscript(FIXTURES / "basic.funscript")
    assert fs.metadata.title == "Test Script"
    assert fs.metadata.creator == "Wombat Tests"
    assert fs.metadata.duration == 5000
    assert "test" in fs.metadata.tags


def test_load_disordered_becomes_sorted():
    fs = load_funscript(FIXTURES / "disordered.funscript")
    ats = [a.at for a in fs.actions]
    assert ats == sorted(ats)


def test_load_duplicate_timestamp_last_wins():
    fs = load_funscript(FIXTURES / "disordered.funscript")
    # at=1000ms (1.0s) appears twice: pos=0 then pos=100 → last wins = 100
    a = fs.actions.at_time(1.0, 0.001)
    assert a is not None and a.pos == 100


def test_load_unknown_top_level_keys_preserved():
    fs = load_funscript(FIXTURES / "extras.funscript")
    assert fs.extra.get("injectedByOtherTool") == "preserve-me"
    assert fs.extra.get("anotherExtraKey") == 42


def test_load_unknown_metadata_keys_preserved():
    fs = load_funscript(FIXTURES / "extras.funscript")
    assert fs.metadata.extra.get("customMetaField") == "also-preserve-me"


def test_load_inverted_flag():
    fs = load_funscript(FIXTURES / "extras.funscript")
    assert fs.inverted is True


def test_load_missing_actions_raises():
    with tempfile.NamedTemporaryFile(suffix=".funscript", mode="w", delete=False) as f:
        json.dump({"version": "1.0"}, f)
        name = f.name
    with pytest.raises(FunscriptError, match="actions"):
        load_funscript(name)


def test_load_invalid_json_raises():
    with tempfile.NamedTemporaryFile(suffix=".funscript", mode="w", delete=False) as f:
        f.write("{not valid json}")
        name = f.name
    with pytest.raises(FunscriptError):
        load_funscript(name)


def test_load_missing_file_raises():
    with pytest.raises(FunscriptError):
        load_funscript("/nonexistent/path/file.funscript")


def test_ms_to_seconds_precision():
    fs = load_funscript(FIXTURES / "basic.funscript")
    # at=100ms → 0.1s exactly
    assert fs.actions[0].at == pytest.approx(0.1)


# ------------------------------------------------------------------ save + round-trip

def _round_trip(src: Path) -> tuple[Funscript, Funscript]:
    fs1 = load_funscript(src)
    with tempfile.NamedTemporaryFile(suffix=".funscript", delete=False) as f:
        tmp = Path(f.name)
    save_funscript(tmp, fs1)
    fs2 = load_funscript(tmp)
    return fs1, fs2


def test_round_trip_actions_match():
    fs1, fs2 = _round_trip(FIXTURES / "basic.funscript")
    assert len(fs1.actions) == len(fs2.actions)
    for a1, a2 in zip(fs1.actions, fs2.actions):
        assert a1.pos == a2.pos
        assert abs(a1.at - a2.at) < 0.001  # within 1ms


def test_round_trip_preserves_extra_keys():
    fs1, fs2 = _round_trip(FIXTURES / "extras.funscript")
    assert fs2.extra.get("injectedByOtherTool") == "preserve-me"
    assert fs2.extra.get("anotherExtraKey") == 42


def test_round_trip_preserves_metadata_extra():
    fs1, fs2 = _round_trip(FIXTURES / "extras.funscript")
    assert fs2.metadata.extra.get("customMetaField") == "also-preserve-me"


def test_round_trip_idempotent():
    # load → save → load → save → load: actions identical at each step
    fs1, fs2 = _round_trip(FIXTURES / "basic.funscript")
    with tempfile.NamedTemporaryFile(suffix=".funscript", delete=False) as f:
        tmp2 = Path(f.name)
    save_funscript(tmp2, fs2)
    fs3 = load_funscript(tmp2)
    for a2, a3 in zip(fs2.actions, fs3.actions):
        assert a2 == a3


def test_save_actions_sorted():
    al = ActionList([Action(3.0, 30), Action(1.0, 10), Action(2.0, 20)])
    fs = Funscript(actions=al)
    with tempfile.NamedTemporaryFile(suffix=".funscript", delete=False) as f:
        tmp = Path(f.name)
    save_funscript(tmp, fs)
    data = json.loads(tmp.read_text())
    ats = [a["at"] for a in data["actions"]]
    assert ats == sorted(ats)


def test_seconds_to_ms_precision():
    # 0.1s → 100ms exactly
    al = ActionList([Action(0.1, 50)])
    fs = Funscript(actions=al)
    with tempfile.NamedTemporaryFile(suffix=".funscript", delete=False) as f:
        tmp = Path(f.name)
    save_funscript(tmp, fs)
    data = json.loads(tmp.read_text())
    assert data["actions"][0]["at"] == 100
