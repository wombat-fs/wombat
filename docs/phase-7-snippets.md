# Phase 7 — Snippet Library

**Goal:** a library of parameterized generators that produce layer content — "drum-beat" rhythms for the `at` timestamps combined with algorithms for the `pos` values — inserted as layers (Phase 6) or over a selection.

**Milestone (definition of done):** open the snippet panel, pick a pattern (e.g. alternating-two-values, or a sine), tune its parameters with a live preview, and insert it as a new layer over a chosen span — the composite curve updates immediately, as one undo step.

Depends on Phase 6 (layers, synthesis) and reuses the Phase 2 domain model.

---

## The design: compose rhythm × position

The README separates two concerns — the **timing** of points and the **position** algorithm at those points. Making them orthogonal and composable gives combinatorial richness from a few primitives:

- A **`Rhythm`** produces the timestamps over a span ("drum-beat patterns for `at`").
- A **`PosAlgorithm`** produces the positions at those timestamps ("algorithms for `pos`"), optionally reading the signal beneath.
- A **`BeatSnippet`** = a `Rhythm` × a `PosAlgorithm`.

Plus a second family for continuous oscillations:

- A **`WaveformSnippet`** emits its own dense sampling of a waveform (sine/triangle/…) over the span, independent of a beat grid.

Both implement one interface — `Snippet.generate(span, base, fps) -> ActionList` — so the UI, insertion, and preview treat them uniformly.

> **Synergy with layers:** the README's "alternating values *added to* a base sinusoid" needs no special snippet — it's a sine `WaveformSnippet` layer plus an alternating `BeatSnippet` layer, both additive, **composed by the Phase 6 layer stack**. Snippets stay simple; layering does the mixing. A convenience combined snippet can exist, but the primitives + stacking already cover it.

---

## Decisions (firm)

| Decision | Choice | Rationale |
|---|---|---|
| Location | pure **`domain/snippets/`**, no Qt | Generators are pure functions of params; headless-testable. |
| Model | composable `Rhythm` × `PosAlgorithm` (`BeatSnippet`) + standalone `WaveformSnippet`, unified by `Snippet.generate` | Matches the README's at/pos split; few primitives, many combinations. |
| UI controls | **`ParamSpec`-driven**, auto-generated | Each generator declares its parameters; the panel builds sliders/inputs generically — no per-snippet UI code. |
| Primary action | **insert as a new layer** in the active channel | Snippets are layer content; insertion is one undo step. |
| Base-dependent pos | sample the **composite of layers below** the insertion point | Lets "offset from the underlying signal" work; the editor supplies the sampler. |
| Parametric layers | **optional/stretch:** a layer may remember its snippet spec for non-destructive regeneration | Powerful, but defer if it complicates Phase 7; the hook is cheap to leave. |

---

## Package additions

```
wombat/domain/snippets/
  __init__.py
  base.py        # Rhythm, PosAlgorithm protocols; Snippet, BeatSnippet, WaveformSnippet; ParamSpec
  rhythms.py     # ConstantBeat, Subdivided, Swing, Euclidean, Accelerando
  positions.py   # Alternate, Constant, Ramp, Random, Sine, Triangle, Square, Sawtooth, AlternateOverBase, FollowBase
  library.py     # named presets + registry
wombat/ui/
  snippet_panel.py   # builder: choose generator, auto-built param controls, live preview, insert
tests/
  test_snippets.py
```

---

## `base.py` — the abstractions

```python
@dataclass
class ParamSpec:
    key: str
    label: str
    kind: Literal["int", "float", "bool", "choice"]
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[str] | None = None

class Rhythm(Protocol):
    @classmethod
    def param_specs(cls) -> list[ParamSpec]: ...
    def beats(self, span: tuple[float, float], fps: float | None) -> np.ndarray: ...   # times in span

class PosAlgorithm(Protocol):
    @classmethod
    def param_specs(cls) -> list[ParamSpec]: ...
    def positions(self, times: np.ndarray,
                  sample_base: Callable[[np.ndarray], np.ndarray] | None) -> np.ndarray: ...

class Snippet(Protocol):
    name: str
    def generate(self, span, *, base: ActionList | None = None,
                 fps: float | None = None, snap_to_frame: bool = False) -> ActionList: ...

@dataclass
class BeatSnippet:
    rhythm: Rhythm
    pos: PosAlgorithm
    name: str = "beat"
    def generate(self, span, *, base=None, fps=None, snap_to_frame=False) -> ActionList:
        times = self.rhythm.beats(span, fps)
        sampler = (lambda ts: values_at(base, ts)) if base is not None else None
        positions = self.pos.positions(times, sampler)
        # optional frame snap, clamp+round pos, build ActionList

@dataclass
class WaveformSnippet:
    waveform: Literal["sine", "triangle", "square", "sawtooth"]
    frequency: float; amplitude: float; center: int; phase: float
    resolution_hz: float = 60.0
    name: str = "waveform"
    def generate(self, span, *, base=None, fps=None, snap_to_frame=False) -> ActionList:
        # dense-sample the waveform over span at resolution (frame-aligned if fps); clamp+round
```

---

## Generators

**Rhythms** (`rhythms.py`):
- `ConstantBeat` — even spacing from BPM or interval.
- `Subdivided` — BPM with N subdivisions per beat.
- `Swing` — alternating long/short (swing ratio).
- `Euclidean` — `pulses` spread over `steps` (Euclidean rhythm) at a BPM.
- `Accelerando` — interval ramps from start to end across the span (tempo glide).

**Position algorithms** (`positions.py`):
- `Alternate(low, high)` — toggle between two values.
- `Constant(value)`, `Ramp(start, end)`, `Random(low, high, seed)` (seeded → deterministic).
- `Sine/Triangle/Square/Sawtooth(amplitude, frequency, center, phase)` — waveform sampled at the beat times.
- `AlternateOverBase(low_offset, high_offset)` — base sampled at each beat + an alternating offset (the README's "alternating added to base").
- `FollowBase(scale, offset)` — derived from the underlying signal.

Each exposes `param_specs()` so the UI builds its controls. Everything vectorized over numpy arrays.

**`library.py`** — named presets (a `Rhythm`+`PosAlgorithm`+default params, or a configured `WaveformSnippet`) with friendly names ("Buzz", "Throb", "Pulse train", "Tease"…), plus a registry the panel enumerates.

---

## Editor integration

Add to `EditorController` (each one undo step; reuse Phase 6 layer ops):

```python
def insert_snippet_as_layer(self, snippet: Snippet, span, *,
                            blend=BlendMode.ADDITIVE, name: str) -> None: ...
def fill_layer_with_snippet(self, layer_index: int, snippet: Snippet, span) -> None: ...
```

The **base sampler** passed to `generate` is `value_at` over the synthesis of the layers **below** the target layer (so base-dependent snippets read the right underlying signal). For a brand-new top layer, that's the current composite.

*(Optional/stretch)* attach the `snippet` + params to the created `Layer` as a `source` spec so the user can reopen the panel and **regenerate** with tweaked params non-destructively; manual edits detach it.

---

## `snippet_panel.py` — the builder UI

A dock/dialog that:
- Lets the user pick a **preset** (from `library`) or build from scratch: choose a rhythm + a pos algorithm, or a waveform.
- **Auto-generates parameter controls** from the selected generators' `param_specs()` (sliders/spinboxes/checkboxes/combos by `kind`).
- Shows a **live preview**: render the generated `ActionList` in a mini-canvas (reuse the timeline lane renderer over the snippet's span); update on any param change.
- Picks the **target span**: the current timeline selection, or explicit start + duration.
- **Insert as layer** (primary) or **Apply over selection** in the active layer — via the editor methods above. Choose blend mode (additive default for modulations, override for replacements).

---

## Testing

- **Rhythms:** `ConstantBeat`/`Subdivided` spacing and count over a span; `Swing` long/short ratio; `Euclidean` distributes `pulses` over `steps` correctly; `Accelerando` spacing is monotonic.
- **Positions:** `Alternate` toggles; `Sine` etc. match analytic samples at the times; `AlternateOverBase` equals base-at-time + offset; `Random` is reproducible per seed; all clamp/round to 0–100.
- **Snippets:** `generate` yields actions strictly within the span; frame-snap rounds to frames; `WaveformSnippet` density matches `resolution_hz`.
- **Base sampling:** a base-dependent snippet over a known base produces the expected sum.
- **ParamSpec:** every generator's defaults instantiate a valid generator; declared ranges are self-consistent.
- **Editor:** `insert_snippet_as_layer` adds one layer and one undo step; the base sampler reflects layers below.
- **Manual/pytest-qt:** preview updates live; insert reflects in the composite.

---

## Acceptance criteria

1. Open the snippet panel, choose "Alternate" over a selection, see a live preview, insert as an additive layer — the composite updates.
2. Insert a sine `WaveformSnippet` over the base; combined with an alternate layer it reproduces "oscillation + beat" purely by stacking.
3. Changing any parameter updates the preview immediately.
4. A base-dependent snippet (`AlternateOverBase`/`FollowBase`) tracks the underlying signal.
5. Insertion is a single undo step; undo removes the whole layer.
6. `test_snippets.py` passes; `ruff`/`mypy` clean; `domain/snippets/` imports neither Qt nor mpv.

## Task checklist for the implementer

- [ ] `snippets/base.py` — `ParamSpec`, `Rhythm`/`PosAlgorithm` protocols, `Snippet`/`BeatSnippet`/`WaveformSnippet`
- [ ] `snippets/rhythms.py` — ConstantBeat, Subdivided, Swing, Euclidean, Accelerando
- [ ] `snippets/positions.py` — Alternate, Constant, Ramp, Random, Sine/Triangle/Square/Sawtooth, AlternateOverBase, FollowBase
- [ ] `snippets/library.py` — presets + registry
- [ ] `EditorController` — `insert_snippet_as_layer`, `fill_layer_with_snippet`, base sampler from layers-below
- [ ] (optional) parametric-layer `source` spec + regenerate
- [ ] `snippet_panel.py` — generator pick, auto param controls, live preview, target span, insert/apply
- [ ] `test_snippets.py`
- [ ] Verify acceptance criteria on Apple Silicon macOS
```
