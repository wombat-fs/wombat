# Phase 9 — Polish & Extensibility (living backlog)

**Goal:** everything that turns the working core (Phases 0–8) into a tool people choose — authoring power, navigation, UX, extensibility, device integration, and quality at scale.

Unlike Phases 0–8, this is **not one ordered deliverable**. It's a backlog of mostly-independent workstreams that can be built in parallel and reprioritized as real use reveals what matters. This document is a **baseline expected to grow** — add items as they surface. Each item is sketched (what / why / reference / rough effort / dependencies), not spec'd to implementation depth; promote an item to its own `docs/phase-9-<item>.md` when it's picked up.

Most of these reuse the clean seams already built (the pure domain core, `EditorController`, the layer model, the timeline). Several were explicitly **deferred from earlier phases** — collected here so nothing is lost.

---

## A. Authoring power

- **Pluggable input modes** *(deferred from Phase 4).* Beyond `DefaultMode`: `AlternatingMode` (auto-alternate top/bottom positions), `DynamicInjectionMode` (speed-targeted point injection), `RecordingMode` (capture mouse/controller motion in real time into one or two axes). The `ScriptingMode` ABC already exists. *Ref:* OFS `OFS_ScriptingMode`. *Effort:* M. *Priority:* high — expected of a real editor.
- **Gamepad / controller input** for recording and navigation. *Ref:* OFS `OFS_ControllerInput` (SDL). *Effort:* M. *Dep:* RecordingMode. *Priority:* medium.
- **Spline preview** *(deferred from Phase 2/3).* Catmull-Rom smoothing for rendering/preview (the device still moves linearly; this is a visual aid and an optional resampling source). *Ref:* OFS `FunscriptSpline`. *Effort:* S. *Priority:* low.

## B. Navigation & structure

- **Chapters / bookmarks.** Named time ranges and point markers on the timeline; jump-to, and clip export per chapter. *Ref:* OFS `OFS_ChapterManager`, `ExportClip`. *Effort:* M. *Priority:* medium-high.
- **Audio waveform underlay** on the timeline (align actions to audio peaks). Needs audio decode (via mpv/ffmpeg) + a cached LOD waveform. *Ref:* OFS `OFS_Waveform`; funscript-tools shows a funscript waveform track. *Effort:* M-L (audio extraction is the cost). *Priority:* medium.
- **Heatmap finalize** *(optional in Phase 3).* If not already shipped, the speed-colored timeline overlay. *Ref:* OFS `FunscriptHeatmap`. *Effort:* S. *Priority:* medium.

## C. Workflow & UX

- **Full keybinding system** *(ad-hoc shortcuts wired earlier).* Centralized, **user-customizable** bindings with a config UI; the existing `keybindings-help` flow can inform it. *Ref:* OFS `OFS_KeybindingSystem`. *Effort:* M. *Priority:* high.
- **Preferences dialog** *(Phase 0 only had a `QSettings` wrapper).* A real settings UI: paths, defaults, rendering options, synthesis resolution, snap defaults. *Ref:* OFS `OFS_Preferences`. *Effort:* M. *Priority:* high.
- **Metadata editor.** Edit `FunscriptMetadata` (title/creator/tags/performers/description/license/notes/duration) per channel/project. *Ref:* OFS `OFS_FunscriptMetadataEditor`. *Effort:* S. *Priority:* medium.
- **Dark / light theming.** Qt palette-based theme toggle (funscript-tools ships dark mode). *Effort:* S. *Priority:* medium.
- **Undo history panel** *(optional in Phase 4).* List of undo/redo descriptions with jump-to. *Ref:* OFS undo history window. *Effort:* S. *Priority:* low.
- **Recent files & session restore**, **auto-backup / crash recovery** (periodic project snapshot; recover on relaunch). *Ref:* OFS `autoBackup`. *Effort:* S-M. *Priority:* medium — cheap insurance.

## D. Extensibility

- **Native Python plugin API.** The big one — the equivalent of OFS's Lua extensions, but Python plugins (no embedding needed since the app is already Python). Expose a stable surface: read/modify a channel's actions, commit-with-undo, control the player, register keybindings, draw a small settings UI. Sandbox/import discipline TBD. *Ref:* OFS `LuaApiReference.md` (the API shape to mirror), `claude-api` skill if any AI-assisted plugins emerge. *Effort:* L. *Priority:* medium — defer until the core API surface (`EditorController`, `Project`) is stable, which it now is.
- **Parametric / regeneratable layers** *(stretch from Phase 7).* A layer remembers the snippet + params that generated it; reopen and regenerate non-destructively; manual edits detach. *Effort:* M. *Priority:* medium.
- **Live-linked derivatives** *(stretch from Phase 8).* Generated channels auto-update when the base changes (vs one-shot). Needs a dependency/dirty-propagation model. *Effort:* M-L. *Priority:* low-medium.
- **Event-timeline lane** *(stretch from Phase 8).* funscript-tools-style draggable event blocks on a dedicated track that realize as layers. *Ref:* funscript-tools Custom Event Builder. *Effort:* M. *Priority:* medium.

## E. Device & integration

- **Device simulator.** A visual widget showing the synthesized position(s) moving in sync with playback — immediate feedback without hardware. *Ref:* OFS `ScriptSimulator`. *Effort:* S-M. *Priority:* high — big usability win, low cost.
- **Real-device output.** Send the synthesized signal to hardware for live preview: Intiface/Buttplug, and/or T-code over serial. Major differentiator for an authoring tool. *Effort:* L. *Priority:* medium — **scope question (see below).**
- **External / WebSocket API.** Programmatic control + integration with video players/devices. *Ref:* OFS `OFS_WebsocketApi`. *Effort:* M. *Priority:* low-medium.

## F. Quality & scale

- **Performance for large scripts.** Incremental/region synthesis (re-synth only changed time spans), timeline render profiling, optional `QOpenGLWidget` repaint backend if `QPainter` culling isn't enough. *Effort:* M-L. *Priority:* as-needed (profile first).
- **Localization infrastructure.** Externalize strings; per-language tables. *Ref:* OFS `OFS_Localization` + `localization.csv`. *Effort:* M. *Priority:* low.
- **Distribution.** Per-OS bundles — macOS `.app` (Apple Silicon), Linux AppImage, Windows installer — including the libmpv dependency. *Ref:* OFS installer/AppImage/snap configs; funscript-tools PyInstaller setup. *Effort:* M per platform. *Priority:* medium — needed before any real release.

---

## Suggested near-term order (once 0–8 land)

A pragmatic "make it feel like a real app" first wave, by value/cost:

1. **Device simulator** (E) — high value, low cost; makes editing feel real.
2. **Keybindings + Preferences** (C) — table stakes for a serious editor.
3. **Input modes: Alternating + Recording** (A) — core authoring ergonomics.
4. **Chapters/bookmarks** (B) and **metadata editor + theming + auto-backup** (C).
5. **Audio waveform** (B) — high value, medium cost.
6. **Distribution** (F) — when approaching a releasable build.
7. **Plugin API** (D) and **real-device output** (E) — larger bets, once the core API and feel are settled.

## Open scope questions (decide before committing effort)

- **Real-device output (E):** is live hardware preview (Intiface/T-code) in scope for Wombat, or is the visual **simulator** sufficient? The README is silent; it focuses on authoring. This changes whether E grows into its own phase.
- **Plugin language/sandbox (D):** unrestricted Python plugins (powerful, trust-based) vs a constrained API surface. Affects security posture.
- **AI-assisted features:** the README puts *AI generation* out of scope — confirm that also excludes lighter AI assists (e.g. suggestion/cleanup), or just full generation.
