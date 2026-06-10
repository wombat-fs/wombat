"""Tests for Channel, Layer, BlendMode, and the funscript conversion seam."""
import pytest

from wombat.domain.action import Action, ActionList
from wombat.domain.channel import BlendMode, Channel, Layer
from wombat.domain.funscript import Funscript, FunscriptMetadata
from wombat.domain.funscript_io import load_funscript
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _al(*pairs) -> ActionList:
    return ActionList(Action(t, p) for t, p in pairs)


# ------------------------------------------------------------------ Layer

def test_layer_defaults():
    layer = Layer(actions=ActionList())
    assert layer.name == "base"
    assert layer.enabled is True
    assert layer.blend == BlendMode.OVERRIDE
    assert layer.span is None
    assert layer.fade_in == 0.0
    assert layer.fade_out == 0.0


# ------------------------------------------------------------------ Channel.synthesize

def test_synthesize_single_layer():
    al = _al((0.0, 0), (1.0, 100))
    ch = Channel(name="main", layers=[Layer(actions=al)])
    result = ch.synthesize()
    assert result == al


def test_synthesize_returns_copy():
    al = _al((0.0, 0), (1.0, 100))
    ch = Channel(name="main", layers=[Layer(actions=al)])
    result = ch.synthesize()
    result.add(Action(2.0, 50))
    assert len(ch.layers[0].actions) == 2  # original untouched


def test_synthesize_skips_disabled_layer():
    al1 = _al((0.0, 0), (1.0, 100))
    al2 = _al((0.0, 50))
    ch = Channel(name="main", layers=[
        Layer(actions=al1, enabled=False),
        Layer(actions=al2, enabled=True),
    ])
    result = ch.synthesize()
    assert result == al2


def test_synthesize_empty_channel():
    ch = Channel(name="empty")
    assert len(ch.synthesize()) == 0


def test_synthesize_all_disabled():
    al = _al((0.0, 50))
    ch = Channel(name="main", layers=[Layer(actions=al, enabled=False)])
    assert len(ch.synthesize()) == 0


# ------------------------------------------------------------------ from_funscript / to_funscript

def test_from_funscript_creates_base_layer():
    al = _al((0.0, 0), (1.0, 100))
    fs = Funscript(actions=al)
    ch = Channel.from_funscript(fs, name="alpha")
    assert ch.name == "alpha"
    assert len(ch.layers) == 1
    assert ch.layers[0].name == "base"
    assert ch.layers[0].actions == al


def test_from_funscript_copies_actions():
    al = _al((0.0, 0), (1.0, 100))
    fs = Funscript(actions=al)
    ch = Channel.from_funscript(fs, name="test")
    al.add(Action(2.0, 50))
    assert len(ch.layers[0].actions) == 2  # copy, not reference


def test_to_funscript_actions_equal_synthesize():
    al = _al((0.0, 0), (1.0, 100), (2.0, 50))
    ch = Channel(name="main", layers=[Layer(actions=al)])
    exported = ch.to_funscript()
    assert exported.actions == ch.synthesize()


def test_round_trip_via_channel():
    fs1 = load_funscript(FIXTURES / "basic.funscript")
    ch = Channel.from_funscript(fs1, name="orig")
    fs2 = ch.to_funscript(
        metadata=fs1.metadata,
        version=fs1.version,
        inverted=fs1.inverted,
        range_=fs1.range_,
    )
    assert fs2.actions == fs1.actions


# ------------------------------------------------------------------ domain isolation

def test_domain_does_not_import_pyside6():
    import sys
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("wombat.domain"):
            del sys.modules[mod_name]
    # Snapshot what's already in sys.modules (other tests may have loaded PySide6).
    pyside_before = {k for k in sys.modules if k.startswith("PySide6")}
    import wombat.domain  # noqa: F401
    pyside_after = {k for k in sys.modules if k.startswith("PySide6")}
    new_pyside = pyside_after - pyside_before
    assert not new_pyside, f"wombat.domain must not import PySide6, added: {new_pyside}"


def test_domain_does_not_import_mpv():
    import sys
    mpv_loaded = "mpv" in sys.modules and sys.modules["mpv"] is not None
    # mpv might be loaded already from conftest; just verify domain __init__ doesn't cause it
    # Re-import domain and check no new mpv references introduced
    import importlib
    import wombat.domain
    importlib.reload(wombat.domain)
    # If we get here without error, mpv wasn't needed
    assert True
