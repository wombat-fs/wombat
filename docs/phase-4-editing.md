# Phase 4 — Editing One Channel

**Goal:** turn the read-only timeline into a real editor for a single channel's base layer — add/move/delete actions, select, undo/redo, copy/paste — with the editing brain (selection + undo + operations) factored cleanly so multi-channel (Phase 5) and layers (Phase 6) slot in without rework.

**Milestone (definition of done):** create a funscript from scratch on a loaded video — click to add points, drag to move them, rubber-band select a run, equalize/invert it, delete, copy/paste, undo and redo through the whole history — then save it as a valid `.funscript`.

Depends on Phase 2 (domain ops/transforms) and Phase 3 (timeline + `Viewport`).

---

## Decisions (firm — these shape three later phases)

| Decision | Choice | Rationale |
|---|---|---|
| Editing brain | a UI-agnostic **`EditorController`** between UI and domain | Mirrors OFS's split (Funscript + UndoSystem + ScriptingMode + timeline). All mutations funnel through one place that snapshots undo and emits change signals. Testable without Qt. |
| Undo model | **snapshot-based with explicit transactions**, multi-channel-ready | Snapshot the affected layer's `ActionList` (+ selection) before an edit; a drag brackets many moves into **one** undo step via `begin/commit`. Simpler than OFS's type-coalescing, and spanning multiple channels in one step is free for Phase 5. |
| Selection storage | a **set of `at` timestamps**, held in `EditorController` (not in the domain `ActionList`) | `at` is unique per action, so it's a stable key across pos-edits; the editor updates it across time-moves. Keeps the Phase 2 domain model pure (selection is an editing concern). |
| Edits target | the **active layer** (the base layer in Phase 4); hit-testing maps display→layer 1:1 | Honors the editing/rendering seam. The timeline still *draws* `synthesize()`; edits go to the layer. With one layer they're equal, so no ambiguity now. |
| Input modes | a `ScriptingMode` ABC + **`DefaultMode` only** this phase | Pluggable authoring modes (Alternating, Recording…) are Phase 9; structure for them now, build one. |
| Frame snapping | optional **snap `at` to nearest video frame** (uses `player.fps`), toggleable | Funscript authoring is frame-oriented; snapping makes points land on frames. Off-by-default toggle. |

---

## Package additions

```
wombat/app/
  undo.py          # UndoStack — snapshot transactions, multi-channel entries
  editor.py        # EditorController — operations + selection, the editing brain
wombat/ui/
  scripting/
    __init__.py
    mode.py        # ScriptingMode ABC + DefaultMode
tests/
  test_undo.py
  test_editor.py
```

Plus two small retrofits:
- **`domain/channel.py`:** add a **synthesis cache** — `Channel.synthesize()` memoizes its result and invalidates on layer mutation, so the timeline doesn't recompute it every repaint. Edits go through `EditorController`, which marks the channel dirty.
- **`ui/timeline/timeline_widget.py`:** add mouse/keyboard editing handlers and selection rendering.

---

## `undo.py` — `UndoStack`

Snapshot-based, transaction-bracketed, ready to span multiple channels in one entry.

```python
@dataclass
class LayerSnapshot:
    channel: Channel          # reference
    layer_index: int
    actions: ActionList       # deep copy at snapshot time
    selection: frozenset[float]

@dataclass
class UndoEntry:
    description: str          # e.g. "Add action", "Move actions", "Equalize"
    snapshots: list[LayerSnapshot]

class UndoStack:
    def __init__(self) -> None: ...
    # discrete edit: snapshot -> mutate -> (auto-finalized)
    def snapshot(self, description: str, targets: list[tuple[Channel, int]],
                 selection: frozenset[float]) -> None: ...
    # gesture (drag): one entry for the whole gesture
    def begin(self, description: str, targets, selection) -> None: ...
    def commit(self) -> None: ...      # finalize the in-progress entry
    def cancel(self) -> None: ...      # discard (e.g. drag aborted)

    def undo(self) -> UndoEntry | None: ...   # restores pre-edit state, pushes inverse to redo
    def redo(self) -> UndoEntry | None: ...
    @property
    def can_undo(self) -> bool: ...
    @property
    def can_redo(self) -> bool: ...
    def descriptions(self) -> tuple[list[str], list[str]]: ...  # for an optional history panel
```

Semantics: `snapshot` captures pre-edit state (so undo restores it) and clears the redo stack. `undo` captures current state into the redo stack before restoring. Restoring re-applies `actions`/`selection` into the referenced layer and invalidates its synthesis cache. A `begin`/`commit` pair captures the pre-gesture state once; intermediate moves don't snapshot.

---

## `editor.py` — `EditorController`

The single funnel for all edits. UI-agnostic; emits Qt signals so the timeline repaints.

```python
class EditorController(QObject):
    actions_changed   = Signal()        # a channel's actions changed -> repaint/export
    selection_changed = Signal()
    history_changed   = Signal()        # undo/redo availability changed

    def __init__(self, session: Session, undo: UndoStack) -> None: ...

    # active target
    @property
    def active_channel(self) -> Channel: ...
    @property
    def active_layer_index(self) -> int: ...   # base (0) in Phase 4

    # --- single-action edits (each its own undo step) ---
    def add_action(self, at: float, pos: int) -> None: ...     # snap if enabled
    def remove_action(self, at: float) -> None: ...
    def edit_action(self, old_at: float, new_at: float, new_pos: int) -> None: ...

    # --- gesture edits (bracketed) ---
    def begin_move(self) -> None: ...
    def move_selection(self, d_seconds: float, d_pos: int) -> None: ...
    def end_move(self) -> None: ...

    # --- selection ---
    def select(self, at: float, additive: bool = False) -> None: ...
    def select_time_range(self, t0: float, t1: float, additive: bool = False) -> None: ...
    def select_all(self) -> None: ...
    def clear_selection(self) -> None: ...
    def select_top(self) / select_mid(self) / select_bottom(self) -> None: ...  # via Phase 2 transforms
    def invert_selection(self) -> None: ...
    @property
    def selection(self) -> frozenset[float]: ...

    # --- transforms over the selection (each an undo step) ---
    def equalize_selection(self) -> None: ...   # transforms.equalize on the selected run
    def invert_positions(self) -> None: ...     # transforms.invert on selection (or whole layer)
    def simplify_selection(self, epsilon: float) -> None: ...

    # --- clipboard ---
    def copy(self) -> None: ...     # store [(at - t0, pos)] for selection
    def cut(self) -> None: ...
    def paste(self, at_playhead: float) -> None: ...        # relative to playhead
    def paste_exact(self) -> None: ...                       # at original absolute times

    # --- history ---
    def undo(self) -> None: ...
    def redo(self) -> None: ...

    # options
    snap_to_frame: bool = False
```

Each mutating method: snapshot (or be inside a begin/commit), mutate `active_channel.layers[i].actions`, invalidate the channel's synthesis cache, emit `actions_changed`. Selection is updated to track moves (when an action's `at` changes, swap the key in the selection set).

---

## `scripting/mode.py` — input modes

```python
class ScriptingMode(ABC):
    @abstractmethod
    def add_point(self, editor: EditorController, at: float, pos: int) -> None: ...
    def name(self) -> str: ...

class DefaultMode(ScriptingMode):
    def add_point(self, editor, at, pos) -> None:
        editor.add_action(at, pos)     # straight passthrough
```

Phase 4 wires only `DefaultMode`. The abstraction exists so Phase 9 can add `AlternatingMode` (alternates top/bottom), `RecordingMode` (real-time capture), etc., without touching the timeline or editor.

---

## Timeline editing interactions (extend `timeline_widget.py`)

Use the Phase 3 `Viewport` for all mapping, and a pixel-radius hit test (`ActionList.at_time` plus a screen-distance check) to find the action under the cursor.

- **Click empty lane area** → active `ScriptingMode.add_point(editor, x_to_time(x), y_to_pos(y))`.
- **Click on an action** → `editor.select(at, additive=Shift/Ctrl held)`.
- **Drag an action** → `editor.begin_move()`, then `move_selection(Δt, Δpos)` per mouse-move (whole selection moves together), `end_move()` on release. One undo step.
- **Drag empty area** → rubber-band; on release `editor.select_time_range(t0, t1)` (and pos bounds if desired).
- **Delete / Backspace** → remove selected.
- **Ctrl+C / X / V** → copy / cut / paste-at-playhead; **Ctrl+Shift+V** → paste exact.
- **Ctrl+Z / Ctrl+Y** → undo / redo (also Edit menu, enabled per `can_undo/redo`).
- **Set-point-at-playhead** keybind → add an action at `player.logical_time` with a default/last pos (keyboard authoring while paused on a frame).
- Optional now (or Phase 9): select top/mid/bottom, equalize, invert keybinds.

Rendering: draw **selected** actions in a distinct color/size; draw the rubber-band rectangle while dragging. Repaint on `actions_changed`/`selection_changed`.

### Frame snapping

When `snap_to_frame` is on and a video is loaded, round `at` to the nearest frame: `round(at / frame_time) * frame_time`. Applies to add and to move-end. No-op when no video or fps unknown.

---

## App wiring

- **File ▸ New Funscript** creates an empty `Channel` bound to the current video and makes it active (so you can author from scratch).
- **File ▸ Save / Save As** writes the active channel via `Channel.to_funscript()` → `save_funscript()` (Phase 2). Track an unsaved-edits flag (set on `actions_changed`, cleared on save) and prompt on close — mirror OFS's close-without-saving dialog.
- Edit menu: Undo/Redo/Cut/Copy/Paste/Select All wired to the editor.
- Optional: an **Undo History** dock listing `descriptions()` (OFS has one) — nice but not required.

> **Forward note (superseded in Phase 5):** this phase's single-channel "New Funscript" / "Save" (writing one channel directly to `.funscript`) is a stepping stone. Phase 5 reorganizes the File menu into **Save Project** (`.wombat`, the editable state) vs **Export Funscripts** (synthesized output), and `EditorController(session: Session)` becomes `EditorController(project: Project)` (the `Session` holder is replaced wholesale). Don't over-invest in the Phase 4 Save UX.

---

## Testing (editor + undo are pure — test them hard)

- **`UndoStack`:** snapshot→mutate→undo restores exactly; redo re-applies; a `begin`/`commit` gesture is one step; `cancel` discards; new edit after undo clears redo; multi-target entry restores all targets together.
- **`EditorController` (headless, mock/stub the player and signals):**
  - add/remove/edit produce correct `ActionList` and undo steps.
  - move updates selection keys correctly; gesture is one undo step.
  - selection ops (range, all, top/mid/bottom, invert) select the right `at` set.
  - equalize/invert/simplify over selection match the Phase 2 transforms applied to the selected run.
  - copy/paste round-trips at the playhead; paste-exact restores absolute times.
  - snap-to-frame rounds `at` to frame boundaries.
- **Synthesis cache:** mutating a layer invalidates it; `synthesize()` reflects the edit; cache hit when unchanged.
- **Widget (manual + optional pytest-qt):** the acceptance flow below.

---

## Acceptance criteria

1. **New Funscript** on a loaded video, then click to add several points — they appear on the timeline aligned to where clicked.
2. Drag a point (and a multi-selection) — moves as one undo step; Ctrl+Z reverts the whole drag, Ctrl+Y reapplies.
3. Rubber-band select a run; Delete removes it; equalize and invert act on the selection.
4. Copy a selection and paste at the playhead; paste-exact restores original times.
5. Undo/redo walks the entire history correctly; Edit-menu items enable/disable appropriately.
6. Save produces a valid `.funscript` that reloads identically (ties back to Phase 2 round-trip).
7. Frame-snap, when on, lands points exactly on frame boundaries.
8. `test_undo.py` / `test_editor.py` pass; `ruff`/`mypy` clean on new code.

## Task checklist for the implementer

- [ ] `undo.py` — `UndoStack` with snapshots, transactions, multi-target entries, descriptions
- [ ] `editor.py` — `EditorController`: edits, gestures, selection, transforms, clipboard, history; signals
- [ ] Selection-tracking across moves (timestamp-key updates)
- [ ] `scripting/mode.py` — `ScriptingMode` ABC + `DefaultMode`
- [ ] `domain/channel.py` retrofit — synthesis cache + invalidation
- [ ] `timeline_widget.py` — mouse/keyboard editing, rubber-band, selection rendering, hit-testing via `Viewport`
- [ ] Frame snapping
- [ ] App wiring — New/Save/Save As, unsaved-edits guard, Edit menu, optional history dock
- [ ] `test_undo.py`, `test_editor.py`
- [ ] Verify acceptance criteria on Apple Silicon macOS
```
