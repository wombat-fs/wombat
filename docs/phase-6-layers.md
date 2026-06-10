# Phase 6 — Layers (the differentiator)

**Goal:** make each channel a real **stack of layers** that synthesizes — with fade transitions and override/additive blending — into the flat action list everything else already consumes. This is Wombat's defining feature and has no OFS equivalent, so the synthesis model is reasoned from first principles below.

**Milestone (definition of done):** stack a layer over a base with a smooth fade and see the synthesized composite curve update live; reorder/blend/span/fade the layers and watch the result change; edit a specific layer's nodes; export the synthesized result to a valid `.funscript`. A channel with only a full-span base layer still synthesizes to *exactly* that base (identity preserved).

Depends on Phases 2–5. Replaces the placeholder `Channel.synthesize()` with the real engine.

---

## The core idea: combine signals, not points

A funscript is a sparse set of `(at, pos)` actions interpreted as a **continuous piecewise-linear signal** via interpolation (Phase 2). Combining sparse point lists directly is ambiguous; combining the continuous signals they represent is well-defined. So:

1. Each enabled layer defines a continuous value `vᵢ(t)` (interpolated from its actions, clamped outside its action range) and a **weight envelope** `wᵢ(t)` ∈ [0,1] from its span + fades (0 outside the span, ramping up over `fade_in`, 1 in the middle, ramping down over `fade_out`).
2. **Fold bottom→top** (base first) into an accumulator:

   ```
   result = 0.0
   for layer in layers (bottom → top, skip disabled, skip w==0 at t):
       w  = wᵢ(t)
       v  = vᵢ(t)
       if layer.blend == OVERRIDE:
           result = lerp(result, v, w)          # crossfade replace
       elif layer.blend == ADDITIVE:
           result += w * (v - layer.center)      # weighted signed offset
   result = clamp(result, 0, 100)
   ```

3. **Re-sample** the folded `result(t)` back into a sparse `ActionList`.

This fold is order-correct, makes fades genuine crossfades, and **preserves identity**: a single full-span (`w≡1`), override, no-fade base gives `lerp(0, base, 1) = base` exactly — so Phases 2–5 keep working unchanged.

### Why additive uses `(v - center)`

Additive layers are modulations *on top of* what's below (a "buzz", a tremor). Adding raw 0–100 values would blow past range. Subtracting a per-layer `center` (default **50**) means a flat layer at its center contributes nothing, and deviations push up/down — matching funscript-tools' bipolar `apply_modulation`. Authors make a snippet oscillate around its center; it adds ±amplitude.

---

## The re-sampling problem (and the answer)

Crossfading/adding piecewise-linear signals with a **varying** weight produces non-linear (quadratic/cubic) segments *inside fade windows* — not exactly representable as a linear funscript. But **outside** every fade ramp, all weights are constant (0 or 1), so the fold is piecewise-linear and representable **exactly**. Therefore:

- **Outside fade windows:** sample only at exact **breakpoints** — the union of action times of the layers that are fully on in that region. Sparse and exact.
- **Inside fade windows:** sample **densely** at `resolution_hz` (frame-aligned when fps is known), then **RDP-simplify** (Phase 2 `simplify_rdp`, small epsilon) to drop redundant points.

Result: sparse where the input is sparse, dense only during transitions, and a simple hand-authored script stays untouched. **Hard edges** (a span boundary with zero fade) would be a true discontinuity a funscript can't represent — enforce a **minimum fade of one frame** (or one sample) at span edges to keep the signal continuous.

---

## Decisions (firm)

| Decision | Choice | Rationale |
|---|---|---|
| Synthesis location | pure **`domain/synthesis.py`**, no Qt | Most important and novel logic in the project; must be headless-testable alongside Phase 2. |
| Fold | continuous bottom→top; override = `lerp(result, v, w)`, additive = `+ w·(v − center)` | Order-correct, real crossfades, identity-preserving. |
| Output sampling | exact breakpoints outside fades; dense + RDP inside fades | Keeps output sparse/editable; only transitions cost points. Reuses Phase 2's RDP. |
| Fade curve | **smoothstep default**, linear optional | README asks for "smooth transitions"; smoothstep feels right. Linear available. |
| Hard edges | enforced **≥ 1-frame fade** at span boundaries | Avoids unrepresentable discontinuities. |
| Additive center | per-layer, **default 50** | Flat layer adds nothing; deviations modulate. |
| Caching | channel-level synthesis cache, invalidated on any layer change | Synthesis is now non-trivial; the timeline paints every frame. |
| Editing view | lane shows the **composite** curve; the **active layer's** own nodes are editable overlays | Like a video editor: see the composite, edit the selected clip. |

---

## Data model extension (`domain/channel.py`)

`Layer` already has `actions, name, enabled, blend, span, fade_in, fade_out` (Phase 2). Add:

```python
class FadeCurve(Enum):
    LINEAR = "linear"
    SMOOTH = "smooth"   # smoothstep

@dataclass
class Layer:
    # ...existing...
    center: int = 50              # additive reference
    fade_curve: FadeCurve = FadeCurve.SMOOTH

    def weight_at(self, t: float, min_fade: float) -> float: ...   # envelope, 0..1
    def value_at(self, t: float) -> float: ...                      # interpolate.value_at(self.actions, t)
```

The `.wombat` schema (Phase 5) already serializes the layer list; just add `center` and `fade_curve` fields (back-compatible — default if absent).

---

## `domain/synthesis.py`

```python
@dataclass
class SynthesisParams:
    resolution_hz: float = 60.0     # dense sampling rate inside fade windows
    simplify_epsilon: float = 0.5   # RDP epsilon (pos units) for dense regions
    fps: float | None = None        # frame-align dense samples + set min_fade

def synthesize(layers: list[Layer], params: SynthesisParams) -> ActionList: ...
```

Algorithm:
1. `min_fade = 1/fps` (or `1/resolution_hz` if no fps). Clamp each layer's effective fades to ≥ `min_fade` at non-open span edges.
2. Build **fade windows**: for each enabled layer, `[span_start, span_start+fade_in]` and `[span_end-fade_out, span_end]`.
3. Build the **sample-time set**:
   - exact breakpoints: action times of layers whose weight is constant 1 over the region between consecutive fade-window boundaries (plus those boundaries themselves);
   - dense samples at `resolution_hz` (frame-aligned if `fps`) within every fade window.
4. Evaluate the fold (above) at each sample time → `(t, pos)` with `pos = round(clamp)`.
5. RDP-simplify the runs that came from dense windows (leave exact breakpoints intact) → final `ActionList`.

Keep it vectorizable: evaluate layer values via `interpolate.values_at` over arrays.

**Signature evolution (reconcile with Phases 2–5):** `Channel.synthesize()` gains an **optional** argument — `synthesize(self, params: SynthesisParams | None = None) -> ActionList`. When omitted, it uses default params (no fps → `min_fade` from `resolution_hz`). The **identity case ignores params entirely**, so every existing no-arg call from Phases 2–5 stays valid. Callers that *have* fps — the timeline and `export_funscripts` — pass `SynthesisParams(fps=player.fps)` for frame-accurate fades; the pure domain stays fps-agnostic (fps is passed in, never stored on the `Channel`). The synthesis **cache** is keyed on `(layer state, params)` and invalidates on any layer mutation.

**Hard requirement / test:** for a channel of one full-span, override, no-fade base layer, `synthesize()` returns the base actions unchanged (identity).

---

## Editing & UI

### Active layer

The active channel now has an **active layer**. `EditorController` gains `active_layer_index` (real, not always 0) and routes all Phase 4 action edits to that layer. Structural layer ops are new (below). Selection becomes per-(channel, layer).

### Layer structural operations (through undo)

Add to `EditorController` — each an undo step; extend the undo snapshot to capture **layer structure** (the channel's layer list), not just one layer's actions:

```python
def add_layer(self, name, *, blend=OVERRIDE, span=None) -> None   # empty layer
def duplicate_layer(self, index) -> None
def remove_layer(self, index) -> None
def reorder_layer(self, src, dst) -> None        # restack = change blend order
def set_blend(self, index, blend) -> None
def set_center(self, index, center) -> None
def set_span(self, index, span) -> None
def set_fades(self, index, fade_in, fade_out) -> None
def set_fade_curve(self, index, curve) -> None
def set_layer_enabled(self, index, enabled) -> None
```

(Snippet-generated layer content arrives in Phase 7; Phase 6 adds empty/duplicated layers, which is enough to exercise synthesis.)

### Timeline: expanded layer view (extend `timeline_widget.py`)

- **Collapsed channel lane** (default): the synthesized **composite** curve, as in Phases 3/5.
- **Expanded channel:** the composite as a summary, then one **sub-lane per layer**:
  - a **span block** with draggable edges (set span);
  - **fade handles** at the block's leading/trailing corners (drag to set `fade_in`/`fade_out`, audio-clip style);
  - a **blend badge** (OVR/ADD) and enable toggle;
  - the layer's own **action nodes**, editable when it's the active layer (reuse Phase 4 interactions, now targeting the active layer); other layers ghosted.
- Expand/collapse toggle per channel.

### Layers panel (extend `channels_panel.py` into a channel→layer tree)

Channels at top level, layers nested beneath. Per layer: name, enable, blend mode, active indicator. Buttons: Add layer, Duplicate, Delete, reorder (drag/up-down = restack), set blend/center, rename. Selecting a layer sets the active layer.

---

## Testing (synthesis is the crown jewel — test it hard)

- **Identity:** single full-span override base → `synthesize()` equals base actions exactly.
- **Override crossfade:** base + a full-strength override layer over `[a,b]` with no fade → result equals base outside, layer inside; with a fade → result crossfades monotonically between them across the fade window (sample and check intermediate values).
- **Additive:** a centered flat layer adds nothing; a layer oscillating ±A around center adds ±A to the base; result clamps at 0/100.
- **Order matters:** swapping two override layers changes the result where they overlap.
- **Sparsity:** sparse inputs with no fades produce a sparse output (action count near the input union, not the dense grid); dense fade regions are RDP-trimmed (bounded count).
- **Continuity:** no zero-length discontinuities; min-fade enforced at hard edges.
- **Caching:** layer mutation invalidates; unchanged channel hits cache.
- **Round-trip:** synthesized output exports to `.funscript` and reloads equal (ms rounding aside).
- **Manual/pytest-qt:** the acceptance flow — drag fades/spans and watch the composite update.

---

## Acceptance criteria

1. Add a layer over a base, give it a span and a smooth fade — the composite curve crossfades into the layer across the fade and back out.
2. Switch a layer between override and additive — override replaces, additive modulates around its center; result stays in 0–100.
3. Reorder layers and see overlap regions change accordingly.
4. Expand a channel; drag span edges and fade handles; edit the active layer's nodes — all reflected live in the composite.
5. A plain single-base channel is visually and numerically identical to Phase 5 (identity holds).
6. Export reproduces the composite as a valid funscript.
7. Undo/redo covers both action edits and structural layer changes.
8. Synthesis test suite passes; `ruff`/`mypy` clean; `synthesis.py` imports neither Qt nor mpv.

## Task checklist for the implementer

- [ ] `domain/channel.py` — extend `Layer` (`center`, `fade_curve`, `weight_at`, `value_at`)
- [ ] `domain/synthesis.py` — the fold + breakpoint/dense sampling + RDP cleanup; `SynthesisParams`
- [ ] `Channel.synthesize()` delegates to the engine + caches; identity guaranteed
- [ ] `.wombat` schema: serialize `center`/`fade_curve` (back-compatible)
- [ ] `EditorController` — `active_layer_index`, per-(channel,layer) selection, structural layer ops via undo
- [ ] Undo snapshot extended to capture layer structure
- [ ] `timeline_widget.py` — expand/collapse, per-layer sub-lanes, span blocks, fade handles, active-layer editing, ghosted others
- [ ] `channels_panel.py` — channel→layer tree with layer management
- [ ] Synthesis test suite (identity, crossfade, additive, order, sparsity, continuity, caching)
- [ ] Verify acceptance criteria on Apple Silicon macOS
```
