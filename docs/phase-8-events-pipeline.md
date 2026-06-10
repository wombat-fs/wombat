# Phase 8 — Event YAML & funscript-tools Integration

**Goal:** ingest funscript-tools' world — load its `event_definitions.yml` and apply those multi-channel events natively, and (optionally) generate its derivative channel set from a base. Both parts reuse Phases 2/6/7; little new infrastructure.

Two independent parts — build in either order:
- **8a — Events:** load `event_definitions.yml`, apply events as multi-channel **layer insertions**.
- **8b — Derivative pipeline:** generate alpha/beta/volume/frequency/pulse… channels from a base by porting funscript-tools' algorithms.

**Milestones:**
- *(8a)* load the repo's `funscript-tools/config.event_definitions.yml`, place an event on the timeline, and have it create the right layers on the right channels with correct waveform/fade/blend.
- *(8b)* generate the standard derivative channels from a base channel and have them appear as editable channels in the project.

Reference material (read these — they are the spec): `funscript-tools/FUNDAMENTAL_OPERATIONS.md` (operation semantics), `funscript-tools/config.event_definitions.yml` (event format), `funscript-tools/processor.py` + `funscript-tools/processing/` (algorithm source of truth), `funscript-tools/PYTHON_GUI_APPLICATION_SPECIFICATION.md` (pipeline params).

---

## The key insight (8a): events ARE layer insertions

A funscript-tools event applies operations to one or more axes over `[start_time_ms, start_time_ms + duration_ms]`. That maps directly onto Wombat's non-destructive layer model:

| funscript-tools | Wombat |
|---|---|
| `apply_modulation` (waveform on an axis) | a `WaveformSnippet` (Phase 7) inserted as a **layer** over the span |
| `mode: additive / overwrite` | layer `blend` = ADDITIVE / OVERRIDE |
| `ramp_in_ms` / `ramp_out_ms` | layer `fade_in` / `fade_out` |
| `axis: volume,volume-prostate` (multi-axis) | one layer per named **channel** |
| `set_value` | constant-value override layer |
| `fade` | ramp layer |
| value in Hz/%/normalized | normalized via the YAML's `normalization` block → 0–100 pos |

So applying an event is **non-destructive** — it adds layers you can then tweak or remove, rather than baking values in. This is the Wombat-native realization of "events that affect several parallel channels," and it's mostly wiring over Phases 6–7.

---

## Decisions (firm)

| Decision | Choice | Rationale |
|---|---|---|
| Event application | **non-destructive layer insertions** across channels | Matches Wombat's philosophy; reuses Phase 6/7; events stay editable/removable. |
| Axis ↔ channel | match event `axis` names to **channel names** (the Phase 5 naming convention) | `volume`, `pulse_frequency`, `alpha`… are already the channel names. Missing channel → warn & skip. |
| Normalization | apply the YAML `normalization` block (axis max + unit) → 0–1 → 0–100 | Faithful to funscript-tools value semantics. |
| Pipeline integration | **port the algorithms** into pure numpy (`domain/pipeline/`), one-shot channel generation | Wombat is Python; porting keeps outputs as editable channels and avoids a subprocess + file round-trip. External-subprocess call is an optional fallback. |
| Pipeline source of truth | `funscript-tools/processing/` + `processor.py` | Port faithfully; don't reinvent the formulas. |
| Event grouping | *optional/stretch:* tag layers created by one event with a group id | Lets the user remove/move a whole event later. Cheap hook; defer the UI. |

---

## Part 8a — Events

### Package

```
wombat/domain/events/
  model.py        # EventDefinition, Operation, NormalizationConfig, EventLibrary
  yaml_loader.py  # parse event_definitions.yml -> EventLibrary
  apply.py        # translate an event (at a start time) -> layer insertions (per-op translators)
wombat/ui/
  events_panel.py # load YAML, list events, place/apply at a span
tests/
  test_events.py
```

### Model & loader

```python
@dataclass
class NormalizationConfig:
    axes: dict[str, tuple[float, str]]   # axis -> (max, unit)
    def normalize(self, axis: str, value: float) -> float: ...   # -> 0..1 (rules per FUNDAMENTAL_OPERATIONS.md)

@dataclass
class Operation:
    type: str                 # "apply_modulation" | "set_value" | "fade" | ...
    axes: list[str]           # parsed from comma-separated `axis`
    params: dict              # raw op params (waveform, frequency, amplitude, mode, ramp_in_ms, ...)

@dataclass
class EventDefinition:
    name: str
    operations: list[Operation]

@dataclass
class EventLibrary:
    normalization: NormalizationConfig
    events: dict[str, EventDefinition]

def load_event_library(path: str) -> EventLibrary: ...
```

Parse the repo's `config.event_definitions.yml` as the canonical example/fixture. Honor the normalization rules exactly as documented (if max==1.0 already normalized; if value ≤ 1.0 and max > 1.0 assume pre-normalized; else divide by max).

### Apply (translate → layers)

```python
def apply_event(editor: EditorController, event: EventDefinition, lib: EventLibrary,
                start: float, group: str | None = None) -> None: ...
```

For each `Operation`, a **per-type translator** builds Wombat content and inserts it as a layer on each target channel (matched by name) over `[start, start + duration]`:

- `apply_modulation` → `WaveformSnippet(waveform, frequency, amplitude→normalized→0..100, center from max_level_offset, phase, duty_cycle)`, blend from `mode`, fades from `ramp_in_ms`/`ramp_out_ms`. (This is exactly the Phase 7 waveform layer.)
- `set_value` → constant override layer at the normalized value.
- `fade` → a ramp layer.
- Add more translators as the YAML uses them; keep a registry `{op_type: translator}` so unknown ops warn rather than crash.

All insertions go through `EditorController` so the whole event application is **one undo step** (wrap in an undo transaction; optionally tag layers with `group`).

### UI — `events_panel.py`

- **Load event definitions…** (defaults to the repo file) → list the available events.
- Pick an event, choose the target span (timeline selection or start+duration), **Apply** → `apply_event`.
- *(Stretch, mirrors funscript-tools' Custom Event Builder):* a dedicated **event lane** on the timeline where event blocks are dragged/resized; applying realizes them as layers. Core requirement is just list + apply-at-span.

---

## Part 8b — Derivative pipeline

Port funscript-tools' generators so Wombat can build the derivative channel set from a base. **Read `funscript-tools/processing/` and `processor.py` for exact formulas** — port faithfully into pure numpy.

### Package

```
wombat/domain/pipeline/
  config.py       # PipelineConfig — the parameter set (mirrors funscript-tools config.json)
  signal_ops.py   # speed, acceleration, normalize, map, limit, invert, mirror, combine(ratio), ramp
  conversions.py  # 1D->2D: Circular, Top-Left-Right, Top-Right-Left, 0-360
  motion_axis.py  # E1-E4 linear-interpolation curves (control points)
  runner.py       # generate the standard derivative channels from a base + config
wombat/ui/
  derivatives_dialog.py   # configure params + choose outputs + generate
tests/
  test_pipeline.py
```

### What to port (faithful to the reference)

- **`signal_ops.py`** — the primitives: windowed **speed** & **acceleration**, **normalize** (max/RMS), **map** to a range, **limit**, **invert**, **mirror**, **combine** two signals by an integer ratio (ratio 3 = 66.7% / 33.3%, per the spec), and the **volume ramp** generator (percentage-per-hour progression).
- **`conversions.py`** — the four 1D→2D algorithms with speed-responsive radius (min-distance-from-center, speed-at-edge-Hz), producing alpha/beta.
- **`motion_axis.py`** — E1–E4 via linear interpolation through control points (the Motion Axis system).
- **`runner.py`** — assembles the standard outputs (alpha, beta, frequency, pulse_frequency, pulse_rise_time, pulse_width, volume, volume-prostate, volume-stereostim, alpha-prostate; or the E-axis variant) from the base, per `PipelineConfig`.

`runner.generate(base: Channel, config: PipelineConfig, fps) -> list[Channel]` — **one-shot**: produces new editable channels added to the project. A **Regenerate** action re-runs from the current base. (Live-linked derivatives that auto-update are a future enhancement.)

> Alternative kept open: an **external-subprocess** path that shells out to an installed funscript-tools and imports the resulting files. Use only if a faithful port of some generator proves impractical; the ported path is primary.

### UI — `derivatives_dialog.py`

- Choose the **base channel** and which outputs to generate.
- Configure the params (the funscript-tools tabs: General/Speed/Frequency/Volume/Pulse/Motion-Axis/Advanced — implement the core set first, structure for the rest), with save/load of a `PipelineConfig`.
- **Generate** → new channels appear in the project (one undo step). **Regenerate** re-runs.

---

## Testing

**8a (events):**
- Load the repo `config.event_definitions.yml` without error; every event parses.
- `NormalizationConfig.normalize`: 100 Hz with max 200 → 0.5; 50% with max 100 → 0.5; already-normalized passthrough.
- `apply_modulation` → a layer with the expected waveform/frequency/amplitude, fades = ramps, blend = mode.
- Multi-axis op creates one layer per named channel; missing channel warns & skips.
- Whole event application is one undo step.

**8b (pipeline):**
- Port correctness vs the reference: feed a known base and compare against funscript-tools output (golden files generated from the actual tool) for speed, 1D→2D geometry, combine-ratio percentages, normalization-to-full-range. Tolerance for float/rounding.
- `runner.generate` produces the expected channel set; outputs export to valid funscripts.

---

## Acceptance criteria

1. *(8a)* Load the repo's event definitions; apply an event at a span — correct layers appear on the named channels (waveform, fades, blend), non-destructively; one Ctrl+Z removes the whole event.
2. *(8a)* A multi-axis event targets several channels at once; values are correctly normalized to 0–100.
3. *(8b)* Generate derivatives from a base; alpha/beta/volume/etc. channels appear and are editable; export reproduces them.
4. *(8b)* Generated output matches funscript-tools within tolerance on the golden-file tests.
5. `test_events.py` / `test_pipeline.py` pass; `ruff`/`mypy` clean; `domain/events/` and `domain/pipeline/` import neither Qt nor mpv.

## Task checklist for the implementer

**8a:**
- [ ] `events/model.py`, `events/yaml_loader.py` — parse the repo YAML incl. normalization
- [ ] `events/apply.py` — per-op translators → layer insertions; registry; one-undo-step application
- [ ] `events_panel.py` — load, list, apply-at-span (event-lane optional)
- [ ] `test_events.py` against the repo `config.event_definitions.yml`

**8b:**
- [ ] `pipeline/signal_ops.py`, `conversions.py`, `motion_axis.py` — faithful numpy ports of `funscript-tools/processing/`
- [ ] `pipeline/config.py`, `runner.py` — params + standard derivative generation, one-shot + regenerate
- [ ] `derivatives_dialog.py` — configure/generate, config save/load
- [ ] `test_pipeline.py` — golden-file comparison vs funscript-tools
- [ ] (optional) external-subprocess fallback path
- [ ] Verify acceptance criteria on Apple Silicon macOS
```
