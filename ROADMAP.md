# Wombat Roadmap

A high-level plan for building Wombat. This is the skeleton — each phase gets fleshed out when we reach it. See `CLAUDE.md` for the tech stack and `OFS/CLAUDE.md` for the architecture ideas being ported from OpenFunscripter.

## Guiding principles

- **Always runnable.** Every phase ends with an app you can launch and demo. No long stretches of dead code.
- **Risk first.** Build the riskiest and most foundational pieces early (video playback, the data model), so surprises surface while they're cheap to fix.
- **Domain core stays pure.** The funscript model knows nothing about Qt or mpv. It's plain Python, fully unit-testable headless. This keeps the valuable logic long-lived and the UI swappable.
- **Design for layers from day one.** Wombat's defining feature is the per-channel layer stack. Even while early phases only use a single base layer, model a `Channel` as a stack so adding real layers later is "allow N > 1," not a rewrite.
- **Port OFS's algorithms, not its rendering.** Reuse the data model, undo, transforms, and player abstraction; reimplement the canvas in Qt.

## Architecture

Four rings, dependencies pointing inward. **The domain core never imports PySide6 or mpv.**

```
┌─────────────────────────────────────────────┐
│ UI (PySide6): windows, timeline canvas,      │  ← knows domain types
│   panels, keybindings                        │
│  ┌────────────────────────────────────────┐  │
│  │ Playback: VideoPlayer over python-mpv  │  │  ← isolated behind interface
│  │  ┌──────────────────────────────────┐  │  │
│  │  │ App services: project lifecycle, │  │  │  ← UI-agnostic orchestration
│  │  │   undo/redo, settings/state      │  │  │
│  │  │  ┌────────────────────────────┐  │  │  │
│  │  │  │ Domain core (pure Python): │  │  │  │  ← no Qt, no mpv, unit-tested
│  │  │  │  actions, channels,        │  │  │  │
│  │  │  │  layers, synthesis,        │  │  │  │
│  │  │  │  transforms, I/O, snippets,│  │  │  │
│  │  │  │  event-YAML engine         │  │  │  │
│  │  │  └────────────────────────────┘  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### Core data model

- **`Action`** — `at` (float **seconds** internally) + `pos` (int 0–100). Milliseconds only at file I/O.
- **`ActionList`** — sorted-by-time container with bisect-based lookups (action-at-time±error, next, previous). Mirrors OFS's `vector_set`.
- **`Layer`** — an `ActionList` plus an envelope: enabled flag, time span, fade-in/out durations, and blend mode (override vs additive).
- **`Channel`** — a name plus an ordered stack of layers (**layer 0 = base**). `synthesize()` folds the stack top-down, applying fades, into a flat `ActionList`.
- **`Project`** — channels + media path + metadata. Saved as JSON (Python's equivalent of OFS's `.ofsp`).

**The key seam:** rendering, playback, export, and heatmap always consume **synthesized output**; editing always targets the **active layer**. Make this explicit from Phase 2 even when synthesis is identity, so layers slot in cleanly at Phase 6.

### Proposed package layout

```
wombat/
  domain/           # pure: no Qt, no mpv
    action.py       # Action, ActionList
    channel.py      # Channel, Layer, synthesis
    funscript_io.py # load/save .funscript (ms ↔ seconds)
    interpolate.py  # spline / value-at-time sampling
    transforms.py   # invert, simplify (RDP), equalize, select top/mid/bottom
    snippets/       # pattern generators
    events/         # funscript-tools YAML engine
  app/              # UI-agnostic services
    project.py      # project lifecycle
    undo.py         # snapshot undo/redo
    settings.py     # app-state vs project-state split
  playback/
    player.py       # VideoPlayer abstraction over python-mpv
  ui/               # PySide6
    main_window.py
    mpv_widget.py   # render-API video widget (see CLAUDE.md sketch)
    timeline/       # channel-lane canvas
    panels/         # layers, snippets, events, metadata
    keybindings.py
  __main__.py
tests/
```

> This layout is **indicative** — a high-level orientation, not exhaustive. The per-phase docs in `docs/` are authoritative for exact module paths and names (e.g. panels live flat in `ui/`, `domain/` also gains `funscript.py`/`synthesis.py`/`pipeline/`, `app/` also gains `editor.py`/`naming.py`).

### Cross-cutting choices

- **Events/decoupling:** prefer Qt signals/slots (natural in PySide6) where OFS uses its event queue. The domain core exposes plain observer callbacks; the UI wires them to signals. No custom global event bus.
- **Undo:** snapshot the editable source (layer data) tagged by operation type, like OFS. Per-channel stacks with app-wide ordering so one Ctrl+Z can span a multi-channel edit.
- **State:** split app settings (window layout, preferences) from project state (per-project settings), like OFS's `OFS_StateManager`.

## Build phases

Each phase is dependency-ordered and ends with a concrete, runnable milestone.

### Phase 0 — Scaffold & run → [`docs/phase-0-scaffold.md`](docs/phase-0-scaffold.md)
Repo, virtualenv, `pyproject.toml` with pinned deps, app entry that opens an empty PySide6 main window with a dock layout.
**Milestone:** `python -m wombat` shows a window.

### Phase 1 — Prove video (highest risk first) → [`docs/phase-1-video.md`](docs/phase-1-video.md)
`MpvWidget` via the libmpv render API (skeleton in `CLAUDE.md`), wrapped in a `VideoPlayer` abstraction: load, play/pause, exact seek, frame-step, and the logical-vs-actual position split from OFS.
**Milestone:** load a video, scrub frame-by-frame, confirm frame-accuracy on the target macOS hardware. De-risks the dependency we deliberated over.

### Phase 2 — Domain core (headless) → [`docs/phase-2-domain-core.md`](docs/phase-2-domain-core.md)
`Action`, `ActionList`, `.funscript` load/save with ms↔seconds conversion, interpolation/spline sampling, and the first transforms (invert, RDP simplify, equalize). `Channel` with a single base layer and an identity `synthesize()`. Unit-tested, no UI.
**Milestone:** round-trip real `.funscript` files; test suite green.

### Phase 3 — Read-only timeline → [`docs/phase-3-timeline.md`](docs/phase-3-timeline.md)
A channel-lane canvas below the video rendering synthesized actions as nodes + connecting lines, with a playhead synced to the player, zoom/pan, and a time ruler. Optional: the speed heatmap.
**Milestone:** open a video plus its funscript and watch the playhead track across the script.

### Phase 4 — Editing one channel → [`docs/phase-4-editing.md`](docs/phase-4-editing.md)
Add / move / delete actions on the active base layer; selection (rubber-band, select top/mid/bottom); undo/redo; copy/paste. Start with a single Default input mode, structured so pluggable modes (Alternating, Recording) can be added later.
**Milestone:** create and edit a funscript from scratch and save it. *Now it's a real editor.*

### Phase 5 — Multi-channel project → [`docs/phase-5-project.md`](docs/phase-5-project.md)
`Project` container: multiple channels, add/remove/rename, active-channel switching, multi-lane display (active highlighted, others dimmed), project save/load, and multi-axis export by file-naming convention.
**Milestone:** edit alpha + beta + volume against one video and export all. *Now it matches OFS's core capability.*

### Phase 6 — Layers (the differentiator) → [`docs/phase-6-layers.md`](docs/phase-6-layers.md)
Promote channels to real layer stacks: the `Layer` envelope (fades + override/additive blend), the synthesizer folding the stack, and the layer-lane UI (drag, resize, reorder — video-editor style). Route edits to the active layer.
**Milestone:** stack a layer over a base with a smooth fade and see the synthesized result. *This is what OFS cannot do.*

### Phase 7 — Snippet library → [`docs/phase-7-snippets.md`](docs/phase-7-snippets.md)
Pattern generators: drum-beat `at` patterns × `pos` algorithms (alternating, sinusoid-over-base, etc.), producing layer content inserted as a layer or over a selection.
**Milestone:** drop a generated snippet onto a channel as a layer.

### Phase 8 — Event/YAML & funscript-tools integration → [`docs/phase-8-events-pipeline.md`](docs/phase-8-events-pipeline.md)
Parse funscript-tools `event_definitions.yml` and apply multi-channel operations (`apply_modulation`, `set_value`, `fade`, …). Optionally wrap the funscript-tools derivative pipeline (1D→2D conversion, generating volume/frequency/pulse channels from a base).
**Milestone:** load an existing event YAML and have it modulate the correct channels.

### Phase 9 — Polish & extensibility → [`docs/phase-9-polish.md`](docs/phase-9-polish.md)
Full keybinding system, preferences, metadata editor, device simulator, a native Python plugin API (the equivalent of OFS's Lua extensions), localization. Ongoing.

## Dependency summary

```
Phase 0 (scaffold)
   ├─► Phase 1 (video) ──────────────┐
   └─► Phase 2 (domain core) ──┬──────┤
                               │      ▼
                               │   Phase 3 (read-only timeline)
                               │      │
                               │      ▼
                               │   Phase 4 (edit one channel)
                               │      │
                               │      ▼
                               │   Phase 5 (multi-channel project)
                               │      │
                               │      ▼
                               └─► Phase 6 (layers)
                                      │
                          ┌───────────┼───────────┐
                          ▼           ▼           ▼
                    Phase 7      Phase 8      Phase 9
                   (snippets)  (event YAML)  (polish)
```
