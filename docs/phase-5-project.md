# Phase 5 — Multi-channel Project

**Goal:** promote the thin `Session` into a real `Project` — multiple channels, channel management, active-channel switching, stacked multi-lane display, project save/load, and multi-axis import/export by filename convention. This is where Wombat reaches OFS's core capability.

**Milestone (definition of done):** open a video, have its sibling `.funscript` files auto-load as separate channels (e.g. alpha/beta/volume), see them stacked as lanes, switch the active channel and edit it while the others stay put, add/remove/rename channels, save the project, reopen it identically, and export all channels back to correctly-named `.funscript` files that reload unchanged.

Depends on Phases 2–4 (`Channel`, timeline, `EditorController`/`UndoStack`).

---

## Decisions (firm)

| Decision | Choice | Rationale |
|---|---|---|
| Project file | a JSON **`.wombat`** file | Python-native; OFS's binary `.ofsp` has no upside here. Human-diffable. |
| Project time unit | store `at` in **float seconds** (not ms) | The project is the editable source of truth; keeping full float precision avoids accumulating ms-rounding across edit sessions. Only **exported `.funscript`** files quantize to ms. |
| Schema shape | channels contain a **`layers` list** from day one | Phase 6 adds real layers without a format migration; Phase 5 just has one base layer per channel. |
| Save vs Export | **Save Project** (`.wombat`, editable state) and **Export Funscripts** (synthesized `.funscript` files) are **distinct** operations | Mirrors OFS's project-save vs funscript-export split. You edit the project; you ship the funscripts. |
| Media path | stored **relative to the project file** | Portability — move the project + media together and paths still resolve. |
| Multi-axis | by **filename-suffix convention**: `base.<channel>.funscript`; the main channel has **no suffix** (`base.funscript`) | Matches the restim/funscript-tools ecosystem (`.alpha.funscript`, `.volume.funscript`, …). Any suffix is a valid channel name. |
| Selection scope | **per-channel** | Switching channels preserves each channel's selection (OFS keeps selection per-script). |
| Undo scope | **one app-wide `UndoStack` per project** | Already multi-target from Phase 4; cross-channel edits land in one history. |
| Lane activation | clicking an **inactive** lane just **activates** it; editing needs the active lane | Prevents accidental edits on the wrong channel (OFS-like). |

---

## Package additions

```
wombat/app/
  project.py     # Project model: channels, active index, save/load (.wombat), path helpers,
                 #   channel management, import/export
  naming.py      # channel-name <-> funscript filename-suffix convention + sibling discovery
wombat/ui/
  channels_panel.py   # right-dock channel list: add/remove/rename/reorder/active/enabled
tests/
  test_project.py
  test_naming.py
```

**Retrofits:**
- `app/session.py` (Phase 3 placeholder) is **replaced by** `Project`. Update `MainWindow`, `EditorController`, and the timeline to take a `Project`.
- `EditorController.active_channel` now reads `project.active_channel`; selection becomes a per-channel dict.
- `timeline_widget.py` renders **N stacked lanes** instead of one.

---

## `project.py` — `Project`

```python
PROJECT_VERSION = 1
PROJECT_EXT = ".wombat"

@dataclass
class ViewState:
    offset: float = 0.0          # persisted timeline scroll (seconds)
    visible_time: float = 5.0    # persisted zoom (seconds across the canvas)

class Project(QObject):
    channels_changed = Signal()    # add/remove/rename/reorder -> rebuild lanes & panel
    active_changed   = Signal(int)

    def __init__(self) -> None: ...

    media_path: str | None         # absolute at runtime
    channels: list[Channel]
    active_index: int
    path: str | None               # .wombat location (None if unsaved)
    view: ViewState                # offset, visible_time (persisted per project)

    # lifecycle
    @classmethod
    def new(cls, media_path: str | None = None) -> "Project": ...
    @classmethod
    def load(cls, path: str) -> "Project": ...
    def save(self, path: str | None = None) -> None: ...    # writes .wombat
    def has_unsaved_edits(self) -> bool: ...

    # channel management
    def add_channel(self, name: str, *, actions: ActionList | None = None) -> Channel: ...
    def import_funscript(self, path: str, name: str | None = None) -> Channel: ...  # add as channel
    def remove_channel(self, index: int) -> None: ...
    def rename_channel(self, index: int, name: str) -> None: ...
    def move_channel(self, src: int, dst: int) -> None: ...
    def set_active(self, index: int) -> None: ...
    @property
    def active_channel(self) -> Channel: ...

    # multi-axis
    def discover_and_load_siblings(self, media_path: str) -> None: ...  # auto-load base.*.funscript
    def export_funscripts(self, out_dir: str | None = None,
                          channels: list[int] | None = None,
                          overwrite: bool = False) -> list[str]: ...

    # path helpers
    def make_relative(self, abs_path: str) -> str: ...   # vs self.path's directory
    def make_absolute(self, rel_path: str) -> str: ...
```

### `.wombat` JSON schema

```json
{
  "wombat_project_version": 1,
  "media": "clip.mp4",
  "active_channel": 0,
  "view": { "offset": 0.0, "visible_time": 5.0 },
  "channels": [
    {
      "name": "alpha",
      "enabled": true,
      "version": "1.0", "inverted": false, "range": 100,
      "metadata": { "...": "FunscriptMetadata fields" },
      "layers": [
        { "name": "base", "enabled": true, "blend": "override",
          "span": null, "fade_in": 0.0, "fade_out": 0.0,
          "actions": [ { "at": 0.10, "pos": 0 }, { "at": 0.50, "pos": 100 } ] }
      ]
    }
  ]
}
```

`at` is seconds (float). `media` is relative to the project file. The `layers` array is single-entry in Phase 5; Phase 6 fills it out.

---

## `naming.py` — multi-axis convention

```python
MAIN_CHANNEL_NAMES = {"orig", "main", "script", ""}   # -> no suffix

def channel_filename(base: str, channel_name: str) -> str: ...
    # ("clip", "alpha") -> "clip.alpha.funscript"
    # ("clip", "orig")  -> "clip.funscript"

def parse_channel_name(filename: str, base: str) -> str | None: ...
    # inverse; returns channel name or None if not a sibling of base

def discover_siblings(media_path: str) -> list[tuple[str, str]]: ...
    # scan the media's directory for base.funscript and base.*.funscript;
    # return [(channel_name, abs_path), ...]
```

Typical channel names from the README: `orig, alpha, beta, volume, frequency, pulse-width, pulse-rise`. Offer these as quick-add presets in the panel, but accept any name.

---

## Multi-lane timeline (extend `timeline_widget.py`)

The widget already renders a **list** of lanes (Phase 3 structure). Now it actually stacks them:

- Divide the lane area into one horizontal band per channel. Either equal bands, or give the **active** channel a taller band; dim inactive lanes (reduced opacity) and full-opacity the active one. Draw a subtle active-lane border.
- Build a **per-lane `Viewport`** sharing `offset`/`visible_time`/`width` (common time axis) but with that lane's `lane_top`/`lane_height`. All x-mapping is shared; only y-mapping differs per lane.
- **Hit-testing:** map cursor `y` → which lane → that channel; then map within the lane. Editing routes to the **active** channel only.
- **Click an inactive lane** → `project.set_active(that_index)` (no edit). A subsequent click in the now-active lane edits (per Phase 4).
- Repaint on `channels_changed` / `active_changed` and the existing `actions_changed`.

The playhead and ruler span all lanes (shared time axis), drawn once on top.

---

## `channels_panel.py` — the right dock

Replaces the Phase 0 placeholder. A list (one row per channel) showing name, enabled checkbox, and active indicator, plus:

- **Add** (with a preset-names dropdown: orig/alpha/beta/volume/frequency/pulse-width/pulse-rise) → `project.add_channel`.
- **Import…** → `project.import_funscript`.
- **Remove**, **Rename** (double-click row), **Reorder** (drag or up/down buttons → `move_channel`).
- Selecting a row → `project.set_active`. Toggling enabled → channel `enabled` (affects export + later synthesis).

Drives and reflects the `Project`; the timeline and editor react via signals.

---

## App wiring (project lifecycle)

- **File ▸ New Project**, **Open Project…** (`.wombat`), **Save Project** / **Save As…**.
- **Open Media…** creates a new project and runs `discover_and_load_siblings` (auto-loads sibling funscripts as channels). If none found, start with one empty base channel.
- **File ▸ Export Funscripts…** → `export_funscripts` (all enabled channels → `base.<name>.funscript` next to the media or a chosen dir), with **overwrite protection** (prompt before clobbering existing files — OFS does).
- Unsaved-edits guard on New/Open/Close, prompting to save the project (carry over the Phase 4 dialog).
- Persist/restore the per-project `view` (zoom/offset) and active channel through save/load.

---

## Testing

- **`Project` round-trip:** save → load reproduces channels, layers, metadata, active index, view state, and the **relative** media path; absolute path resolves correctly from a moved project dir.
- **Path helpers:** `make_relative`/`make_absolute` are inverses across directories.
- **`naming`:** `channel_filename`/`parse_channel_name` round-trip; main-channel names map to no-suffix; `discover_siblings` finds the right set in a temp dir with mixed files.
- **Export:** writes the expected filenames; each reloads equal to the channel's `synthesize()` (within ms rounding); overwrite protection respected.
- **Channel management:** add/remove/rename/reorder keep `active_index` valid; per-channel selection survives an active-channel switch.
- **Manual:** the acceptance flow below.

---

## Acceptance criteria

1. Open a video with sibling `clip.alpha.funscript` / `clip.beta.funscript` / `clip.volume.funscript`; all load as stacked lanes.
2. Click a lane (or panel row) to activate it; edits land only on the active channel; others unchanged.
3. Add a channel from a preset, rename it, reorder it, remove one — panel and timeline stay in sync.
4. Save the project, close, reopen — identical (channels, view, active).
5. Export Funscripts → correctly-named files appear; reopening them reproduces the channels; existing files prompt before overwrite.
6. Undo history spans edits across different channels in one stack; per-channel selection is preserved on switch.
7. `test_project.py` / `test_naming.py` pass; `ruff`/`mypy` clean.

## Task checklist for the implementer

- [ ] `project.py` — `Project` model, `.wombat` save/load, path helpers, channel management, import/export
- [ ] `naming.py` — suffix convention + sibling discovery
- [ ] Replace `session.py`; rewire `MainWindow`/`EditorController`/timeline to `Project`
- [ ] Per-channel selection in `EditorController`
- [ ] `timeline_widget.py` — stacked lanes, per-lane `Viewport`, lane hit-testing, click-to-activate
- [ ] `channels_panel.py` — channel list dock with add/import/remove/rename/reorder/active/enabled
- [ ] Project lifecycle menu actions + Open Media auto-discovery + Export with overwrite protection
- [ ] Persist per-project view + active channel
- [ ] `test_project.py`, `test_naming.py`
- [ ] Verify acceptance criteria on Apple Silicon macOS
```
