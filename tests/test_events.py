"""Tests for Phase 8a — event definitions loading and application.

Covers:
  - NormalizationConfig.normalize rules
  - yaml_loader: parse the repo config.event_definitions.yml
  - translate_event: apply_modulation → Layer, apply_linear_change → Layer
  - Multi-axis steps create one layer per axis
  - Missing channel warns and skips (via EditorController.apply_event_layers)
  - Whole event application is one undo step
  - WaveformSnippet duty_cycle
"""
from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wombat.domain.events.apply import translate_event
from wombat.domain.events.model import (
    EventDefinition,
    EventLibrary,
    NormalizationConfig,
    Step,
)
from wombat.domain.events.yaml_loader import load_event_library

# Path to the reference YAML (shipped in the repo)
_YAML = Path(__file__).parent.parent / "funscript-tools" / "config.event_definitions.yml"


# ===================================================================== fixtures

@pytest.fixture
def norm() -> NormalizationConfig:
    return NormalizationConfig(axes={
        "pulse_frequency": (120.0, "Hz"),
        "pulse_width": (100.0, "%"),
        "frequency": (1200.0, "Hz"),
        "volume": (1.0, "normalized"),
    })


@pytest.fixture
def library(norm: NormalizationConfig) -> EventLibrary:
    return EventLibrary(normalization=norm, events={}, groups=[])


# ===================================================================== NormalizationConfig

class TestNormalizationConfig:
    def test_max_one_passes_through(self, norm: NormalizationConfig) -> None:
        # volume max=1.0 → no conversion
        assert norm.normalize("volume", 0.3) == pytest.approx(0.3)

    def test_max_one_passes_through_large_value(self, norm: NormalizationConfig) -> None:
        # Even values > 1.0 pass through when max=1.0
        assert norm.normalize("volume", 1.5) == pytest.approx(1.5)

    def test_pre_normalized_small_value(self, norm: NormalizationConfig) -> None:
        # pulse_frequency max=120 > 1.0; value=0.5 ≤ 1.0 → pre-normalized
        assert norm.normalize("pulse_frequency", 0.5) == pytest.approx(0.5)

    def test_divide_by_max(self, norm: NormalizationConfig) -> None:
        # 100 Hz / 120 max = 0.8333…
        assert norm.normalize("pulse_frequency", 100.0) == pytest.approx(100.0 / 120.0)

    def test_pulse_width(self, norm: NormalizationConfig) -> None:
        # 50% / 100 max = 0.5
        assert norm.normalize("pulse_width", 50.0) == pytest.approx(0.5)

    def test_frequency(self, norm: NormalizationConfig) -> None:
        # 600 Hz / 1200 max = 0.5
        assert norm.normalize("frequency", 600.0) == pytest.approx(0.5)

    def test_unknown_axis_passthrough(self, norm: NormalizationConfig) -> None:
        assert norm.normalize("alpha", 0.7) == pytest.approx(0.7)

    def test_negative_value(self, norm: NormalizationConfig) -> None:
        # -10 Hz / 120 max = -0.0833…
        assert norm.normalize("pulse_frequency", -10.0) == pytest.approx(-10.0 / 120.0)

    def test_fundamental_operations_examples(self, norm: NormalizationConfig) -> None:
        # 100 Hz with max 200 Hz → 0.5  (FUNDAMENTAL_OPERATIONS.md example)
        n2 = NormalizationConfig(axes={"pf": (200.0, "Hz")})
        assert n2.normalize("pf", 100) == pytest.approx(0.5)
        # 50% with max 100% → 0.5
        n3 = NormalizationConfig(axes={"pw": (100.0, "%")})
        assert n3.normalize("pw", 50) == pytest.approx(0.5)
        # Already normalized (max=1.0) → passthrough
        n4 = NormalizationConfig(axes={"vol": (1.0, "normalized")})
        assert n4.normalize("vol", 0.3) == pytest.approx(0.3)
        # 600 Hz with max 1200 → 0.5
        n5 = NormalizationConfig(axes={"freq": (1200.0, "Hz")})
        assert n5.normalize("freq", 600) == pytest.approx(0.5)


# ===================================================================== yaml_loader

@pytest.mark.skipif(not _YAML.exists(), reason="reference YAML not present")
class TestYamlLoader:
    def test_load_without_error(self) -> None:
        lib = load_event_library(str(_YAML))
        assert lib is not None

    def test_normalization_parsed(self) -> None:
        lib = load_event_library(str(_YAML))
        assert "pulse_frequency" in lib.normalization.axes
        assert "volume" in lib.normalization.axes
        max_val, unit = lib.normalization.axes["volume"]
        assert max_val == pytest.approx(1.0)
        assert unit == "normalized"

    def test_events_non_empty(self) -> None:
        lib = load_event_library(str(_YAML))
        assert len(lib.events) > 0

    def test_all_events_parse(self) -> None:
        lib = load_event_library(str(_YAML))
        # Every event should have at least one step
        for name, ev in lib.events.items():
            assert isinstance(ev.steps, list), f"{name} has no steps list"
            assert len(ev.steps) > 0, f"{name} has zero steps"

    def test_known_events_present(self) -> None:
        lib = load_event_library(str(_YAML))
        for name in ("cum", "edge", "stay", "tranquil", "mcb_submit", "mcb_edge"):
            assert name in lib.events, f"Expected event {name!r} not found"

    def test_multi_axis_step_parsed(self) -> None:
        lib = load_event_library(str(_YAML))
        # 'cum' step 2 targets 'volume,volume-prostate'
        cum = lib.events["cum"]
        multi = [s for s in cum.steps if len(s.axes) > 1]
        assert multi, "Expected at least one multi-axis step in 'cum'"
        assert "volume" in multi[0].axes
        assert "volume-prostate" in multi[0].axes

    def test_default_params_resolved_in_step(self) -> None:
        lib = load_event_library(str(_YAML))
        cum = lib.events["cum"]
        # $duration_ms should resolve to 15000 in each step's params
        for step in cum.steps:
            assert step.params.get("duration_ms") == 15000

    def test_groups_parsed(self) -> None:
        lib = load_event_library(str(_YAML))
        assert len(lib.groups) > 0
        names = [g.name for g in lib.groups]
        assert any("MCB" in n for n in names)


# ===================================================================== translate_event

class TestTranslateEvent:
    def _make_modulation_event(self, mode: str = "additive") -> tuple[EventDefinition, EventLibrary]:
        norm = NormalizationConfig(axes={"volume": (1.0, "normalized")})
        step = Step(
            operation="apply_modulation",
            axes=["volume"],
            start_offset_ms=0,
            params={
                "waveform": "sin",
                "frequency": 9.0,
                "amplitude": 0.1,
                "max_level_offset": 0.15,
                "duration_ms": 5000,
                "ramp_in_ms": 500,
                "ramp_out_ms": 500,
                "mode": mode,
            },
        )
        ev = EventDefinition(name="test_mod", default_params={}, steps=[step])
        lib = EventLibrary(normalization=norm, events={"test_mod": ev})
        return ev, lib

    def _make_linear_event(self, mode: str = "additive") -> tuple[EventDefinition, EventLibrary]:
        norm = NormalizationConfig(axes={"pulse_frequency": (120.0, "Hz")})
        step = Step(
            operation="apply_linear_change",
            axes=["pulse_frequency"],
            start_offset_ms=0,
            params={
                "start_value": 60.0,
                "end_value": 80.0,
                "duration_ms": 10000,
                "ramp_in_ms": 500,
                "ramp_out_ms": 500,
                "mode": mode,
            },
        )
        ev = EventDefinition(name="test_lin", default_params={}, steps=[step])
        lib = EventLibrary(normalization=norm, events={"test_lin": ev})
        return ev, lib

    # --- apply_modulation ---

    def test_modulation_additive_returns_additive_layer(self) -> None:
        ev, lib = self._make_modulation_event(mode="additive")
        insertions = translate_event(ev, lib, start_ms=0.0)
        assert len(insertions) == 1
        ch_name, layer = insertions[0]
        assert ch_name == "volume"
        from wombat.domain.channel import BlendMode
        assert layer.blend == BlendMode.ADDITIVE

    def test_modulation_overwrite_returns_override_layer(self) -> None:
        ev, lib = self._make_modulation_event(mode="overwrite")
        insertions = translate_event(ev, lib, start_ms=0.0)
        _, layer = insertions[0]
        from wombat.domain.channel import BlendMode
        assert layer.blend == BlendMode.OVERRIDE

    def test_modulation_fades_set(self) -> None:
        ev, lib = self._make_modulation_event()
        _, layer = translate_event(ev, lib, start_ms=0.0)[0]
        assert layer.fade_in == pytest.approx(0.5)
        assert layer.fade_out == pytest.approx(0.5)

    def test_modulation_span_from_start_plus_duration(self) -> None:
        ev, lib = self._make_modulation_event()
        # start_ms = 2000, duration = 5000 → span = (2.0, 7.0)
        _, layer = translate_event(ev, lib, start_ms=2000.0)[0]
        assert layer.span is not None
        assert layer.span[0] == pytest.approx(2.0)
        assert layer.span[1] == pytest.approx(7.0)

    def test_modulation_actions_non_empty(self) -> None:
        ev, lib = self._make_modulation_event()
        _, layer = translate_event(ev, lib, start_ms=0.0)[0]
        assert len(layer.actions) > 0

    def test_modulation_amplitude_normalization(self) -> None:
        # amplitude=0.1, volume max=1.0 → normalized=0.1 → pos amplitude=10
        # center should be ~50 + (mlo_norm - amp_norm)*100 = 50 + (0.15 - 0.1)*100 = 55
        ev, lib = self._make_modulation_event(mode="additive")
        _, layer = translate_event(ev, lib, start_ms=0.0)[0]
        # Layer center for additive = 50
        assert layer.center == 50

    # --- apply_linear_change ---

    def test_linear_additive_blend(self) -> None:
        ev, lib = self._make_linear_event(mode="additive")
        _, layer = translate_event(ev, lib, start_ms=0.0)[0]
        from wombat.domain.channel import BlendMode
        assert layer.blend == BlendMode.ADDITIVE

    def test_linear_override_blend(self) -> None:
        ev, lib = self._make_linear_event(mode="overwrite")
        _, layer = translate_event(ev, lib, start_ms=0.0)[0]
        from wombat.domain.channel import BlendMode
        assert layer.blend == BlendMode.OVERRIDE

    def test_linear_two_anchor_actions(self) -> None:
        ev, lib = self._make_linear_event()
        _, layer = translate_event(ev, lib, start_ms=0.0)[0]
        assert len(layer.actions) == 2

    def test_linear_fades(self) -> None:
        ev, lib = self._make_linear_event()
        _, layer = translate_event(ev, lib, start_ms=0.0)[0]
        assert layer.fade_in == pytest.approx(0.5)
        assert layer.fade_out == pytest.approx(0.5)

    def test_linear_overwrite_values_normalized(self) -> None:
        # 60 Hz / 120 max = 0.5, end 80/120 = 0.667
        # OVERRIDE: start_pos = round(0.5*100)=50, end_pos=round(0.667*100)=67
        ev, lib = self._make_linear_event(mode="overwrite")
        _, layer = translate_event(ev, lib, start_ms=0.0)[0]
        actions = list(layer.actions)
        assert actions[0].pos == 50
        assert actions[1].pos == 67

    # --- multi-axis ---

    def test_multi_axis_creates_one_layer_per_axis(self) -> None:
        norm = NormalizationConfig(axes={"volume": (1.0, "normalized"), "volume-prostate": (1.0, "normalized")})
        step = Step(
            operation="apply_modulation",
            axes=["volume", "volume-prostate"],
            params={
                "waveform": "sin",
                "frequency": 15.0,
                "amplitude": 0.05,
                "max_level_offset": 0.1,
                "duration_ms": 3000,
                "mode": "additive",
            },
        )
        ev = EventDefinition(name="multi", default_params={}, steps=[step])
        lib = EventLibrary(normalization=norm, events={"multi": ev})
        insertions = translate_event(ev, lib, start_ms=0.0)
        assert len(insertions) == 2
        ch_names = [ch for ch, _ in insertions]
        assert "volume" in ch_names
        assert "volume-prostate" in ch_names

    def test_unknown_operation_warns_and_skips(self) -> None:
        norm = NormalizationConfig(axes={})
        step = Step(operation="unknown_op", axes=["volume"], params={"duration_ms": 1000})
        ev = EventDefinition(name="bad", default_params={}, steps=[step])
        lib = EventLibrary(normalization=norm, events={"bad": ev})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            insertions = translate_event(ev, lib, start_ms=0.0)
        assert insertions == []
        assert any("unknown_op" in str(w.message) for w in caught)

    def test_group_tag_in_layer_name(self) -> None:
        ev, lib = self._make_modulation_event()
        _, layer = translate_event(ev, lib, start_ms=0.0, group="mygroup")[0]
        assert "mygroup" in layer.name

    def test_start_offset_applied(self) -> None:
        norm = NormalizationConfig(axes={"volume": (1.0, "normalized")})
        step = Step(
            operation="apply_modulation",
            axes=["volume"],
            start_offset_ms=200,
            params={
                "waveform": "sin", "frequency": 9.0, "amplitude": 0.1,
                "max_level_offset": 0.0, "duration_ms": 5000, "mode": "additive",
            },
        )
        ev = EventDefinition(name="offset_ev", default_params={}, steps=[step])
        lib = EventLibrary(normalization=norm, events={"offset_ev": ev})
        _, layer = translate_event(ev, lib, start_ms=1000.0)[0]
        # step start = (1000 + 200) / 1000 = 1.2 s
        assert layer.span[0] == pytest.approx(1.2)


# ===================================================================== editor integration

class TestEditorApplyEventLayers:
    """apply_event_layers inserts layers into matching channels as ONE undo step."""

    def _make_project_with_channels(self, names: list[str]):
        from wombat.app.project import Project
        from wombat.domain.channel import Channel, Layer
        from wombat.domain.action import ActionList
        proj = Project.new()
        for n in names:
            ch = Channel(name=n, layers=[Layer(actions=ActionList(), name="base")])
            proj.channels.append(n)  # won't work — need to use proper API
        return proj

    def _setup_editor(self, channel_names: list[str]):
        from wombat.app.editor import EditorController
        from wombat.app.project import Project
        from wombat.app.undo import UndoStack
        from wombat.domain.action import ActionList
        from wombat.domain.channel import Channel, Layer

        proj = Project.new()
        for n in channel_names:
            ch = Channel(name=n, layers=[Layer(actions=ActionList(), name="base")])
            proj.channels.append(ch)

        player = MagicMock()
        player.frame_time = 1.0 / 30.0
        undo = UndoStack()

        editor = EditorController(proj, player, undo)
        return editor, proj, undo

    def test_apply_inserts_layers(self) -> None:
        editor, proj, undo = self._setup_editor(["volume", "alpha"])
        from wombat.domain.action import ActionList
        from wombat.domain.channel import BlendMode, Layer

        layer = Layer(actions=ActionList(), name="ev:volume", blend=BlendMode.ADDITIVE,
                      span=(0.0, 5.0), fade_in=0.5, fade_out=0.5)
        editor.apply_event_layers([("volume", layer)], description="Test event")

        assert len(proj.channels[0].layers) == 2  # base + event layer
        assert proj.channels[1].layers.__len__() == 1  # alpha unchanged

    def test_apply_is_one_undo_step(self) -> None:
        editor, proj, undo = self._setup_editor(["volume", "alpha"])
        from wombat.domain.action import ActionList
        from wombat.domain.channel import BlendMode, Layer

        layer_v = Layer(actions=ActionList(), name="ev:volume", blend=BlendMode.ADDITIVE,
                        span=(0.0, 5.0))
        layer_a = Layer(actions=ActionList(), name="ev:alpha", blend=BlendMode.ADDITIVE,
                        span=(0.0, 5.0))

        assert not undo.can_undo
        editor.apply_event_layers(
            [("volume", layer_v), ("alpha", layer_a)],
            description="Apply 2-channel event",
        )
        assert undo.can_undo
        # Count undo entries: should be exactly 1
        assert len(undo._undo) == 1

    def test_undo_removes_all_event_layers(self) -> None:
        editor, proj, undo = self._setup_editor(["volume", "alpha"])
        from wombat.domain.action import ActionList
        from wombat.domain.channel import BlendMode, Layer

        layer_v = Layer(actions=ActionList(), name="ev:v", blend=BlendMode.ADDITIVE, span=(0.0, 5.0))
        layer_a = Layer(actions=ActionList(), name="ev:a", blend=BlendMode.ADDITIVE, span=(0.0, 5.0))
        editor.apply_event_layers([("volume", layer_v), ("alpha", layer_a)])

        editor.undo()

        # Both channels should be back to single base layer
        assert len(proj.channels[0].layers) == 1
        assert len(proj.channels[1].layers) == 1

    def test_unknown_channel_warns_and_skips(self) -> None:
        editor, proj, undo = self._setup_editor(["volume"])
        from wombat.domain.action import ActionList
        from wombat.domain.channel import BlendMode, Layer

        layer = Layer(actions=ActionList(), name="ev:ghost", blend=BlendMode.ADDITIVE,
                      span=(0.0, 5.0))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            editor.apply_event_layers([("does-not-exist", layer)])
        assert any("does-not-exist" in str(w.message) for w in caught)
        # volume channel unchanged
        assert len(proj.channels[0].layers) == 1

    def test_empty_insertions_no_undo_entry(self) -> None:
        editor, proj, undo = self._setup_editor(["volume"])
        editor.apply_event_layers([])
        assert not undo.can_undo


# ===================================================================== WaveformSnippet duty_cycle

class TestWaveformSnippetDutyCycle:
    def test_default_duty_cycle_is_50pct(self) -> None:
        from wombat.domain.snippets.base import WaveformSnippet
        snip = WaveformSnippet(waveform="square", frequency=1.0, amplitude=50.0, center=50)
        actions = snip.generate((0.0, 2.0))
        vals = [a.pos for a in actions]
        high = sum(1 for v in vals if v > 50)
        low = sum(1 for v in vals if v < 50)
        assert abs(high - low) <= 3  # roughly equal

    def test_low_duty_cycle_mostly_low(self) -> None:
        from wombat.domain.snippets.base import WaveformSnippet
        snip = WaveformSnippet(waveform="square", frequency=1.0, amplitude=50.0,
                               center=50, duty_cycle=0.05)
        actions = snip.generate((0.0, 2.0))
        vals = [a.pos for a in actions]
        low_count = sum(1 for v in vals if v < 50)
        high_count = sum(1 for v in vals if v > 50)
        assert low_count > high_count * 5  # at least 5× more low than high

    def test_high_duty_cycle_mostly_high(self) -> None:
        from wombat.domain.snippets.base import WaveformSnippet
        snip = WaveformSnippet(waveform="square", frequency=1.0, amplitude=50.0,
                               center=50, duty_cycle=0.95)
        actions = snip.generate((0.0, 2.0))
        vals = [a.pos for a in actions]
        high_count = sum(1 for v in vals if v > 50)
        low_count = sum(1 for v in vals if v < 50)
        assert high_count > low_count * 5


# ===================================================================== round-trip: load yaml + translate

@pytest.mark.skipif(not _YAML.exists(), reason="reference YAML not present")
class TestRoundTrip:
    def test_apply_cum_event(self) -> None:
        lib = load_event_library(str(_YAML))
        ev = lib.events["cum"]
        insertions = translate_event(ev, lib, start_ms=0.0)
        assert len(insertions) > 0
        # Should have one layer per axis per step
        ch_names = [ch for ch, _ in insertions]
        assert "pulse_frequency" in ch_names
        assert "volume" in ch_names
        assert "volume-prostate" in ch_names

    def test_apply_mcb_edge_ce(self) -> None:
        lib = load_event_library(str(_YAML))
        ev = lib.events["mcb_edge_ce"]
        insertions = translate_event(ev, lib, start_ms=5000.0)
        ch_names = [ch for ch, _ in insertions]
        assert "alpha" in ch_names
        assert "beta" in ch_names

    def test_all_events_translate_without_error(self) -> None:
        lib = load_event_library(str(_YAML))
        for name, ev in lib.events.items():
            try:
                insertions = translate_event(ev, lib, start_ms=0.0)
            except Exception as exc:
                pytest.fail(f"translate_event raised for {name!r}: {exc}")
