# Phase 9 — Native Python Plugin API (design note)

**Goal:** let third parties extend Wombat with Python plugins — the equivalent of OFS's Lua extensions, but with no language embedding (the app is already Python). A plugin can read/modify a channel's actions, write to its own non-destructive layer, control the player, run heavy work off the GUI thread safely, and present a small settings UI.

**Status:** design only. Promote sections to code when picked up. Depends on a stable `EditorController` / `Project` / layer model — all of which now exist (Phases 4–8).

This note is the fleshed-out version of the "Native Python plugin API" bullet in [phase-9-polish.md](phase-9-polish.md) §D.

---

## What the audit decided (and why)

We surveyed the real OFS plugin ecosystem before designing this: the OFS [Lua API](../OFS/LuaApiReference.md) (the de-facto spec of what plugins *could* do), the v3 API docs, community extensions (Autotune, the FM-script-converter, MTFG), and Zalunda's **FunscriptToolbox** source (the most ambitious OFS integration). Three findings shaped the design:

1. **No Process escape-hatch.** OFS's most powerful plugins (MTFG, FunscriptToolbox) shell out to a native binary via the Process API. But that boundary is a *language* boundary, not a *compute-isolation* one — OFS is C++/Lua and can't host heavy numeric code. Wombat is Python: motion tracking, audio analysis, ML, etc. are `opencv`/`numpy`/`torch` calls that run **in-process**. FunscriptToolbox's `server_connection.lua` is ~190 lines of hand-rolled async RPC over temp files, built solely to work around Lua's inability to host or talk to such code. We don't inherit that problem, so we don't expose `CreateProcess`.

2. **Threading is a safety contract, not a convenience.** Heavy work must run off the GUI thread, but a worker thread must **never** touch Qt widgets or the domain model (same rule as the mpv `update_cb` in [CLAUDE.md](../CLAUDE.md)). So instead of handing plugins raw `threading.Thread`, we give a **managed task primitive** that runs work on a pool and guarantees the result callback fires on the GUI thread. This is exactly the offload-and-callback pattern FunscriptToolbox reimplements by hand.

3. **Write-to-a-layer instead of shadow lists.** FunscriptToolbox's `virtual_actions.lua` (~260 lines) maintains its own parallel "ghost actions" list, repeatedly inserting/removing them from the one flat OFS script and computing "zones" to avoid clobbering the user's real actions. **Wombat's layer stack does this natively.** A plugin writes to its own layer; the user sees it composited via `synthesize()`; parameter tweaks re-render the layer; "commit" = flatten. The zone/overlap machinery disappears because layers compose instead of fighting over one list.

**Out of scope for v1:** Process API, device/output access (not in Wombat yet), `multiprocessing` (see Threading §, "GIL reality"). Re-evaluate device access if/when real-device output (phase-9 §E) lands.

---

## Module layout

```
wombat/
  plugins/
    __init__.py
    api.py          # the stable public surface: WombatPlugin base, PluginContext, decorators
    manifest.py     # plugin metadata + discovery (name, version, entry, capabilities)
    loader.py       # discover, import, instantiate, enable/disable; per-plugin error isolation
    tasks.py        # PluginTask: run-on-worker + GUI-thread callback (wraps QThreadPool)
    ui.py           # declarative settings-panel spec → built into a Qt widget by the host
    registry.py     # live registry of loaded plugins, their keybindings and menu entries
  ui/
    plugins_panel.py   # "Plugins" menu + per-plugin settings dock (host-rendered)
```

Plugins live in a user directory (mirrors OFS's `extensions/`), one package per plugin:

```
~/.config/wombat/plugins/         # platform-appropriate (QStandardPaths)
  motion_assist/
    plugin.toml                   # manifest
    __init__.py                   # defines the WombatPlugin subclass
    ...                           # plugin's own modules, vendored deps optional
```

`plugin.toml`:

```toml
[plugin]
name = "Motion Assist"
id = "motion_assist"              # unique, used for storage/keybinding namespacing
version = "0.1.0"
entry = "motion_assist:MotionAssistPlugin"   # module:class
api = "1"                         # plugin API major version this targets
capabilities = ["edit_actions", "write_layer", "player_read", "async_tasks"]
```

`capabilities` is declarative intent (surfaced to the user at enable time and usable for future sandboxing); it is not yet an enforced permission boundary in v1.

---

## Lifecycle

Mirror OFS's lifecycle but Qt-native: drop the per-frame `update(delta)` in favor of signals. A plugin subclasses `WombatPlugin`:

```python
from wombat.plugins.api import WombatPlugin, PluginContext, action_command

class MotionAssistPlugin(WombatPlugin):
    def on_load(self, ctx: PluginContext) -> None:
        """Called once when the plugin is enabled. Register commands/keybindings,
        connect to signals, allocate resources. ctx is the only handle to the app."""
        self.ctx = ctx
        ctx.on_active_channel_changed(self._refresh)

    def on_unload(self) -> None:
        """Called when disabled/app-closing. Cancel running tasks, disconnect, free."""

    def settings_panel(self) -> "PanelSpec | None":
        """Return a declarative settings UI, or None for no panel. See GUI §."""
        ...
```

`update(delta)` has no equivalent — anything that needs to react does so via `PluginContext` signal hooks (`on_actions_changed`, `on_active_channel_changed`, `on_playhead_moved`, `on_script_changed`). These wrap the existing `EditorController` signals (`actions_changed`, `selection_changed`, `layer_structure_changed`, plus a playhead signal from the player). The host owns the connections and tears them down on unload, so a buggy plugin can't leak listeners.

---

## The public surface: `PluginContext`

`PluginContext` is the single, stable, documented facade a plugin is given. It deliberately does **not** expose `EditorController` directly — that's an internal app object whose signature can change. The facade wraps it and presents a curated, versioned API. Everything that mutates the document goes through here so undo, cache invalidation, and signals stay correct (the host already enforces this — see `EditorController` docstring: "All writes go through here: snapshot undo, mutate the active layer, invalidate the synthesis cache, emit signals").

### Script / action editing

Maps onto `EditorController` and the domain `ActionList`. All edits are automatically wrapped in a single undo step.

```python
ctx.channels                       # -> list[ChannelView]  (read-only views)
ctx.active_channel                 # -> ChannelView | None
ch.synthesized()                   # -> list[Action]  (flattened, what plays/exports)
ch.layers                          # -> list[LayerView]
layer.actions                      # -> tuple[Action, ...]  (immutable snapshot)

# Edits — each call is one undo step; pass a label for the undo history:
ctx.edit(label="Smooth", target=layer) as edit:   # context manager = one snapshot
    edit.add(at, pos)              # seconds, 0..100  (ms↔s conversion is at file boundary only)
    edit.remove(at)
    edit.set_pos(at, pos)
    edit.clear()
# on exit: snapshot pushed, cache invalidated, actions_changed emitted once

ctx.closest_action(layer, t)             # -> Action | None
ctx.closest_action_before(layer, t)      # OFS parity helpers — used constantly
ctx.closest_action_after(layer, t)
ctx.selection                            # -> frozenset[float]  (selected `at`s on active layer)
```

`Action` is the domain dataclass (float seconds + int pos 0–100), handed out as immutable copies. Plugins build plain `Action`/tuples and pass them in; they never mutate live model objects (the OFS "actions aren't ordinary tables" footgun simply doesn't exist because we copy).

The `ctx.edit(...)` context manager is the key ergonomic: it opens one undo snapshot (`self._undo.snapshot(label, targets, selection)`), applies all mutations, invalidates the channel's `_synthesis_cache`, and emits `actions_changed` exactly once on exit — so a plugin doing 10k edits produces one undo entry and one repaint, not 10k.

### Write to a layer (the FunscriptToolbox `virtual_actions` replacement)

This is the recommended path for *generated* content (motion-derived strokes, pattern fills, derivatives). Instead of inserting actions into the user's layer and tracking what's "yours," create/own a layer:

```python
layer = ctx.create_layer(name="Motion Assist", blend=BlendMode.OVERRIDE, span=(t0, t1))
with ctx.edit(label="Regenerate", target=layer) as edit:
    edit.clear()
    for a in generated:
        edit.add(a.at, a.pos)
```

- **Non-destructive:** the user's existing actions live on other layers and are never touched. No "zone" computation, no overlap-avoidance against user data.
- **Live re-render:** on a parameter change, `edit.clear()` + re-add. The synthesis cache invalidates and the composited result updates. This is what `virtual_actions:update()` does manually, for free.
- **Preview vs commit:** a layer with `enabled=True` is already a live preview (it's in `synthesize()`). "Commit" = flatten the layer into the base (a host operation; expose `ctx.flatten_layer(layer)`), or just leave it as a layer — Wombat's model has no reason to force flattening the way OFS does.
- **Provenance:** the `Layer` dataclass already carries `snippet`/`snippet_entry_name`/`event_name`/`event_param_overrides` fields for re-editable generated layers. Add a parallel `plugin_id` + `plugin_params` pair so a plugin-generated layer can be reopened and regenerated (ties into "Parametric / regeneratable layers", §D).

Amplitude-scaling / top-bottom-offset math like `virtual_actions.lua` lines 170–200 is `pos`-algorithm territory — it belongs in the snippet/synthesis library ([phase-7-snippets.md](phase-7-snippets.md)), reusable by plugins via `ctx`, not reimplemented per plugin.

### Player

Read + control, no frame pixel data in v1 (a plugin that needs frames opens the video file itself via its own `cv2.VideoCapture` — same as MTFG):

```python
ctx.player.position         # seconds (logical position — last requested seek)
ctx.player.duration
ctx.player.fps
ctx.player.is_playing
ctx.player.video_path        # str | None
ctx.player.play(toggle_or_bool)
ctx.player.seek(seconds)     # absolute + exact
```

### Async tasks (the threading infrastructure)

The managed primitive that replaces both raw threads and the Process API:

```python
def heavy(report):                 # runs on a QThreadPool worker
    for i, chunk in enumerate(chunks):
        if report.cancelled: return None
        report.progress(i / len(chunks), f"frame {i}")
        result = expensive(chunk)  # numpy/opencv/torch — releases the GIL
    return result

ctx.run_async(
    heavy,
    on_done=lambda result: self._apply(result),   # GUARANTEED on the GUI thread
    on_error=lambda exc: ctx.log.error(exc),
    label="Detect motion",                          # shown in a host progress UI
)
```

Contract, enforced by the host:
- `heavy` runs on a worker. It **must not** touch `ctx.edit`, the model, or any Qt widget.
- `on_done` / `on_error` are marshalled to the GUI thread (queued signal → slot), so they *may* call `ctx.edit` and update UI. This is the only safe place to write results back.
- Returns a `TaskHandle` with `.cancel()`; `on_unload` should cancel outstanding handles.
- The host shows progress/cancel UI from the `label` + `report.progress`, so plugins don't each build one (FunscriptToolbox builds its own status string by hand).

**GIL reality:** threads genuinely parallelize for native-extension work (numpy/opencv/torch release the GIL); pure-Python CPU-bound loops will not. That covers the realistic plugin workloads (all the OFS-precedent ones are native-backed). `multiprocessing` is deliberately omitted from v1 — it would reintroduce the cross-process IPC problem we just designed away. Revisit only if a concrete pure-Python CPU-bound plugin needs it.

### Logging & storage

```python
ctx.log.info(...) / .warning(...) / .error(...)   # -> a host "Plugin Log" panel (OFS parity)
ctx.storage                                        # per-plugin persistent dict (JSON-backed,
                                                   # namespaced by plugin id) for settings/state
ctx.plugin_dir                                     # Path to this plugin's install dir (read)
```

---

## Commands & keybindings

OFS plugins register "dynamic" keybindings in `init()`. We do the same, integrated with the central keybinding system ([phase-9-polish.md](phase-9-polish.md) §C):

```python
class MotionAssistPlugin(WombatPlugin):
    def on_load(self, ctx):
        ctx.register_command(
            id="generate",                 # namespaced -> "motion_assist.generate"
            title="Generate strokes here",
            handler=self._generate,
            default_key=None,              # user assigns in the keybinding UI
        )
```

Commands appear under a **Plugins** menu (grouped per plugin) and in the keybinding editor for user-assignable shortcuts. Command handlers run on the GUI thread; long work inside them must use `ctx.run_async`.

---

## Settings UI (declarative, not immediate-mode)

OFS exposes a per-frame ImGui `gui()`. In Qt that maps badly — we use a **declarative panel spec** that the host renders into a real `QWidget` once and keeps in a dock. The plugin describes controls and gets change callbacks:

```python
from wombat.plugins.ui import PanelSpec, Slider, IntInput, Checkbox, Button, Group

def settings_panel(self):
    return PanelSpec([
        Group("Amplitude", [
            Slider("min_pct", "Min % filled", 0, 100, value=self.cfg.min_pct),
            Slider("center", "Amplitude center", 0, 100, value=self.cfg.center),
        ]),
        IntInput("top_offset_ms", "Top point offset (ms)", value=self.cfg.top_offset),
        Checkbox("enable_logs", "Verbose logs", value=False),
        Button("regenerate", "Regenerate", on_click=self._regenerate),
    ], on_change=self._on_setting_changed)
```

- Control kinds map onto the OFS GUI surface we audited (`Text`, `Button`, `Input`/`InputInt`, `Drag`/`DragInt`, `Slider`/`SliderInt`, `Checkbox`, `Combo`, `CollapsingHeader`→`Group`, `Tooltip`, `Separator`, disabled regions). That coverage is enough for every audited plugin.
- `on_change(key, value)` fires on edits; `Button.on_click` for actions. Both run on the GUI thread.
- The host owns layout/styling so plugins inherit theming (§C dark/light) for free and can't break the window.
- Values persist via `ctx.storage`.

A plugin that wants a fully custom widget can return a `RawWidget(factory)` escape hatch, but the declarative path is the default and the documented one.

---

## Discovery, loading & isolation

- `loader.py` scans the plugins dir at startup, parses each `plugin.toml`, and lists them in the Plugins panel. Like OFS, **plugins are disabled by default** and the user enables them.
- Each plugin is imported in the host process (no separate VM — Python has no cheap equivalent of Lua's per-extension VM, and the value isn't worth subprocess overhead). Isolation is by discipline + error-boundary, not by sandbox:
  - Every call into a plugin (lifecycle, command handler, task callback, setting change) is wrapped so an exception is logged to the Plugin Log and the plugin is flagged "errored" rather than crashing Wombat.
  - `on_load` failures disable the plugin with a visible reason (mirrors FunscriptToolbox's "missing .exe → show status + tooltip" UX).
- **Security posture (v1):** plugins are arbitrary Python with full process privileges — same trust model as OFS Lua extensions and any desktop plugin system. Document this plainly: *installing a plugin = running its code.* `capabilities` in the manifest is advisory now; a real sandbox (import restrictions, capability gating) is a future item, not a v1 promise. Do not overstate isolation.

---

## API versioning

- `plugin.toml` declares `api = "1"`. The host exposes `PLUGIN_API_VERSION`. Major-version mismatch → refuse to load with a clear message.
- `PluginContext` is the compatibility boundary: keep it additive within a major version. Internal churn in `EditorController` is absorbed by the facade, not leaked to plugins.

---

## Worked example: "Motion Assist" (MTFG / FunscriptToolbox, done the Wombat way)

To show the design end-to-end, here's how the flagship OFS plugin category collapses:

1. **No server process, no file IPC.** Motion extraction is `cv2` in `ctx.run_async`. The ~190-line `server_connection.lua` transport is deleted; the ~260-line `virtual_actions.lua` shadow-list is deleted.
2. User scrubs to a spot, hits the **Generate** command (a keybinding they assigned).
3. The handler reads `ctx.player.position` / `video_path`, kicks off `ctx.run_async(extract_motion, on_done=...)` with a progress label.
4. `on_done` (GUI thread) opens `ctx.create_layer(span=...)` and writes the derived strokes via `ctx.edit`. The user immediately sees them composited.
5. Tweaking the amplitude sliders in the declarative panel calls `_regenerate`, which re-runs `ctx.edit(clear + add)` on the *same* layer. Live preview, non-destructive, fully undoable.
6. Happy with it? Leave it as a layer, or `ctx.flatten_layer(...)`.

Same capability as the most ambitious OFS plugin, with ~450 lines of accidental complexity replaced by the layer model and one async primitive.

---

## Build order

1. `PluginContext` facade over `EditorController`/player + `WombatPlugin` base + loader/manifest (no UI yet) — validate against a trivial "invert active layer" plugin.
2. `run_async` task primitive + Plugin Log panel.
3. `create_layer`/`edit`/`flatten_layer` layer-write path + provenance fields.
4. Declarative settings panel + Plugins menu + keybinding integration.
5. Port a real Motion-Assist-style plugin as the proof and as living API documentation.
