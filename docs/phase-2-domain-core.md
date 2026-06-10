# Phase 2 — Domain Core (headless)

**Goal:** the pure-Python funscript model — actions, the sorted action container, file I/O, interpolation, the first transforms, and the `Channel` abstraction — with no Qt and no mpv. This is the most valuable, longest-lived code in the project; it gets the most test coverage.

**Milestone (definition of done):** load real `.funscript` files, round-trip them losslessly (within millisecond rounding), and pass a unit-test suite covering the model, I/O, interpolation, and transforms. No UI involved — everything runs under `pytest`.

Independent of Phase 1 (can be built in parallel). Depends only on Phase 0's scaffold.

---

## Decisions (firm — rationale matters here, this is the foundation)

| Decision | Choice | Rationale |
|---|---|---|
| Time unit | `Action.at` is **float seconds** internally | Matches OFS; ms is a file-format detail. Convert only in `funscript_io`. |
| Storage | `ActionList` = **sorted list of frozen `Action` dataclasses + `bisect`** lookups | Faithful port of OFS's `vector_set` (O(log n) search, O(n) insert — same as a contiguous set). Keeps single-action editing and undo snapshots simple. |
| Bulk numerics | numpy **escape hatch**, not primary storage | `to_arrays()`/`from_arrays()` let RDP, interpolation, synthesis, heatmap go vectorized without forcing columnar storage on the editing API. Revisit only if profiling demands. |
| `pos` type | **int 0–100** in the stored model; float only in interpolation/synthesis intermediates, quantized back to int at the boundary | Matches the file format and OFS; layer math stays precise without polluting the canonical type. |
| I/O vs editable | **`Funscript`** (file-format DTO) is separate from **`Channel`** (editable, owns layers) | Clean seam: synthesized output → `Funscript` → file. Channel/layer growth in Phases 5–6 doesn't disturb I/O. |
| Unknown JSON keys | **Preserved** on round-trip | OFS's own code flags this as a wanted-but-missing feature (`Funscript.h`: "should retain metadata injected by other programs without overwriting it"). We do it from day one. |
| Interpolation | **Linear is canonical**; spline optional/deferred | Devices move linearly between actions — that's the true semantics. Catmull-Rom spline is a rendering nicety for later. |
| `inverted` / `range` | **Preserved** but **not applied** to actions in Phase 2 | Most tools ignore them; honoring them is a later concern. Round-trip must not lose them. |

---

## Package additions

```
wombat/domain/
  __init__.py
  action.py        # Action, ActionList
  funscript.py     # Funscript (DTO), FunscriptMetadata
  funscript_io.py  # load_funscript / save_funscript, FunscriptError
  interpolate.py   # value_at / values_at (linear); optional spline
  transforms.py    # invert, simplify_rdp, equalize, offset/scale, top/mid/bottom
  channel.py       # Layer, Channel, BlendMode, synthesize()
tests/
  fixtures/        # sample .funscript files
  test_action.py
  test_funscript_io.py
  test_interpolate.py
  test_transforms.py
  test_channel.py
```

Optional dev dep worth adding: `hypothesis` (property-based tests are a great fit for the container/interpolation invariants). `numpy` becomes a runtime dep this phase.

---

## `action.py`

### `Action`

```python
@dataclass(frozen=True, slots=True, order=False)
class Action:
    at: float    # seconds
    pos: int     # 0..100

    def __post_init__(self) -> None: ...  # optional: clamp/validate pos
```

Frozen + hashable. Edits produce new instances (matches OFS's set-keyed-by-time model). Ordering by time is handled by `ActionList`, not `Action.__lt__`, to avoid ambiguity.

### `ActionList`

A container kept **sorted by `at`, unique by `at`**. Inserting at an existing exact timestamp **replaces** the action there. (Timestamps are floats; for hit-testing "near a time" use `at_time` with an error margin — don't rely on float equality.)

```python
class ActionList:
    def __init__(self, actions: Iterable[Action] = ()) -> None: ...   # sorts, dedups by at

    # sequence access
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[Action]: ...
    def __getitem__(self, i: int) -> Action: ...        # by index, sorted order
    def __eq__(self, other: object) -> bool: ...

    # editing (return None; mutate in place — callers snapshot for undo)
    def add(self, action: Action) -> None: ...           # replace if same at
    def remove(self, action: Action) -> None: ...
    def remove_at(self, at: float) -> None: ...

    # lookups (bisect-based, O(log n)) — mirror OFS semantics:
    def at_time(self, t: float, max_error: float) -> Action | None: ...  # nearest within ±error
    def closest(self, t: float) -> Action | None: ...                    # nearest, any distance
    def next_after(self, t: float) -> Action | None: ...                 # first with at > t
    def before(self, t: float) -> Action | None: ...                     # last with at < t
    def index_range(self, t0: float, t1: float) -> tuple[int, int]: ...  # [lo, hi) covering window

    # bulk / numeric escape hatch
    def to_arrays(self) -> tuple[np.ndarray, np.ndarray]: ...   # (at: float64, pos: int32)
    @classmethod
    def from_arrays(cls, at: np.ndarray, pos: np.ndarray) -> "ActionList": ...

    def copy(self) -> "ActionList": ...
```

`index_range` is what the timeline uses to draw only the visible window — implement with `bisect` on a cached key array.

---

## `funscript.py`

```python
@dataclass
class FunscriptMetadata:
    type: str = "basic"
    title: str = ""
    creator: str = ""
    script_url: str = ""
    video_url: str = ""
    tags: list[str] = field(default_factory=list)
    performers: list[str] = field(default_factory=list)
    description: str = ""
    license: str = ""
    notes: str = ""
    duration: int = 0   # ms, as in the format

@dataclass
class Funscript:
    actions: ActionList
    metadata: FunscriptMetadata = field(default_factory=FunscriptMetadata)
    version: str = "1.0"
    inverted: bool = False
    range_: int = 100
    extra: dict = field(default_factory=dict)   # preserved unknown top-level keys
```

`Funscript` is the file-format object. `Channel` (below) is built from it and exports back to it.

---

## `funscript_io.py`

```python
class FunscriptError(Exception): ...

def load_funscript(path: str | Path) -> Funscript: ...
def save_funscript(path: str | Path, fs: Funscript) -> None: ...
```

**Load:**
- Parse JSON; raise `FunscriptError` on malformed JSON or missing `actions`.
- Each action: `at_ms` → `at = at_ms / 1000.0`; `pos` clamped to 0–100. Sort by time; drop exact-duplicate timestamps (keep last).
- Read `version`, `inverted`, `range`, and a `metadata` object if present.
- **Capture every top-level key not otherwise consumed into `Funscript.extra`** (and any unknown keys inside `metadata` too, if practical) so save can write them back.

**Save:**
- `at` → `round(at * 1000)` as int ms. Emit actions sorted, as `{"pos": int, "at": int}`.
- Write `version`, `inverted`, `range`, `metadata`.
- Re-emit `extra` keys. Order: known keys first, then `extra`.
- Round-trip guarantee: `load(save(load(f))) == load(f)` for actions (within ms rounding) and preserves unknown keys.

Provide fixtures in `tests/fixtures/`: a couple of small hand-written `.funscript` files, one with `metadata` + an injected unknown key, one with out-of-order/duplicate timestamps to exercise normalization. A real-world file (drop one in) is a bonus.

---

## `interpolate.py`

Linear interpolation is the canonical funscript semantics.

```python
def value_at(actions: ActionList, t: float) -> float: ...
    # bracket t between two actions, linear-interp pos; clamp to endpoints outside range.
    # empty list -> a defined default (e.g. 0.0 or 50.0 — pick and document).

def values_at(actions: ActionList, times: np.ndarray) -> np.ndarray: ...
    # vectorized (np.interp over to_arrays()); used by rendering/heatmap/synthesis.

# Optional / deferred:
def spline_value_at(actions: ActionList, t: float) -> float: ...   # Catmull-Rom, mark as stretch
```

`values_at` should agree with `value_at` at sample points (test this).

---

## `transforms.py`

All pure: take an `ActionList` (or a contiguous run), return a **new** `ActionList`. No mutation — composes with snapshot undo.

```python
def invert(actions: ActionList, range_: int = 100) -> ActionList: ...      # pos -> range_ - pos
def offset_time(actions: ActionList, seconds: float) -> ActionList: ...
def offset_pos(actions: ActionList, delta: int) -> ActionList: ...          # clamped
def scale_pos(actions: ActionList, factor: float, pivot: int = 50) -> ActionList: ...

def simplify_rdp(actions: ActionList, epsilon: float) -> ActionList: ...
    # Ramer–Douglas–Peucker on the (at, pos) polyline. epsilon in pos units.
    # Always keep first/last. Return the reduced list. (OFS's SIMPLIFY.)

def equalize(actions: ActionList) -> ActionList: ...
    # redistribute timestamps evenly between first and last, positions unchanged.
    # (OFS EqualizeSelection — typically applied to a selected run.)

# Lower priority (selection helpers — pure predicates over the list):
def top_points(actions: ActionList) -> ActionList: ...     # local maxima
def bottom_points(actions: ActionList) -> ActionList: ...  # local minima
def mid_points(actions: ActionList) -> ActionList: ...      # points between extrema
```

RDP and `scale_pos`/`equalize` are good candidates to implement via the numpy escape hatch.

---

## `channel.py`

The editable unit. Phase 2 builds the structure; real multi-layer folding is **Phase 6** — keep the method signatures stable so that phase only fills in logic.

```python
class BlendMode(Enum):
    OVERRIDE = "override"
    ADDITIVE = "additive"

@dataclass
class Layer:
    actions: ActionList
    name: str = "base"
    enabled: bool = True
    # envelope — present now, honored in Phase 6:
    blend: BlendMode = BlendMode.OVERRIDE
    span: tuple[float, float] | None = None   # None = whole timeline
    fade_in: float = 0.0                        # seconds
    fade_out: float = 0.0

@dataclass
class Channel:
    name: str
    layers: list[Layer] = field(default_factory=list)   # layers[0] = base

    def synthesize(self) -> ActionList: ...
        # Phase 2: single enabled base layer -> return a copy of its actions.
        #          (>1 layer may raise NotImplementedError or just return base for now.)
        # Phase 6: fold the stack top-down honoring blend/span/fades.
        #          Phase 6 also adds an optional `params: SynthesisParams | None = None`
        #          arg; no-arg calls (Phases 2-5) stay valid (identity ignores params).

    @classmethod
    def from_funscript(cls, fs: Funscript, name: str) -> "Channel": ...   # base layer = fs.actions
    def to_funscript(self, metadata: FunscriptMetadata | None = None) -> Funscript: ...
        # uses synthesize() for the actions
```

**The seam in action:** everything downstream (render, playback, export, heatmap) consumes `Channel.synthesize()`; editing targets a specific `Layer`. In Phase 2 synthesize is effectively identity, but wiring callers through it now means Phase 6 changes nothing outside `channel.py`.

---

## Testing (the heart of this phase)

- **I/O round-trip:** load → save → load equals original actions (within ms rounding); unknown keys preserved; ms↔seconds exactness (`100` → `0.1` → `100`).
- **`ActionList`:** stays sorted & unique; `add` at existing time replaces; `at_time` honors the error margin and picks the nearest; `next_after`/`before`/`closest` correct at boundaries; empty/single-element/duplicate-time edge cases; `index_range` covers exactly the window.
- **Interpolation:** endpoints, midpoints, outside-range clamping; `values_at` matches `value_at` at sample points; empty-list behavior.
- **Transforms:** `invert(invert(x)) == x`; `simplify_rdp` reduces count and every dropped point stays within `epsilon` of the kept polyline; `equalize` yields uniform spacing and preserves endpoints & positions.
- **Channel:** single-layer `synthesize()` equals the base actions; `from_funscript`/`to_funscript` round-trip.
- **Property-based (optional, hypothesis):** generate random valid action sets; assert sortedness/uniqueness invariants and interpolation monotonicity within a segment.

Loose performance sanity (not a gate): load/save/interpolate/simplify on a ~100k-action script completes in well under a second via the numpy paths.

---

## Acceptance criteria

1. `from wombat.domain import ...` exposes `Action`, `ActionList`, `Funscript`, `Channel`, the I/O and transform functions.
2. Real `.funscript` files load, round-trip losslessly (ms rounding aside), and preserve unknown keys.
3. The full `pytest` suite passes; `ruff`/`mypy` clean on `domain/`.
4. No import of PySide6 or mpv anywhere under `domain/` (add a test that asserts this, or a ruff rule).

## Task checklist for the implementer

- [ ] `action.py` — `Action`, `ActionList` with bisect lookups + numpy escape hatch
- [ ] `funscript.py` — `Funscript`, `FunscriptMetadata`
- [ ] `funscript_io.py` — load/save with ms↔seconds, normalization, unknown-key preservation, `FunscriptError`
- [ ] `interpolate.py` — `value_at`, `values_at` (spline optional)
- [ ] `transforms.py` — invert, offsets, scale, `simplify_rdp`, `equalize` (top/mid/bottom lower priority)
- [ ] `channel.py` — `Layer`, `Channel`, `BlendMode`, identity `synthesize()` + funscript conversion
- [ ] `tests/fixtures/` sample files + full test modules above
- [ ] Guard test/lint rule: `domain/` imports neither PySide6 nor mpv
- [ ] Verify acceptance criteria
