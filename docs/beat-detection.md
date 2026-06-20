# Beat Detection

**Goal:** detect musical beats/downbeats from a loaded video's audio via the external [`beat_this_cpp`](https://github.com/mosynthkey/beat_this_cpp) binary, surface them as a timeline overlay, and wire them into the two places they pay off — **snap-to-beat** and the **snippet rhythm system**. `.beats` import/export falls out for free as the serialization of the in-memory grid.

This is a cross-cutting feature, not a roadmap phase. It depends on the audio waveform pipeline (`wombat/audio/`) and the snippet system (Phase 7).

---

## Decisions (firm)

- **Not a plugin.** The Phase 9 plugin API is modeled on OFS's Lua extensions — a scripting surface for user-authored operations. Beat detection is a heavyweight native dependency (binary + ~83 MB ONNX model), i.e. a core feature, not a user script. Building it through a not-yet-designed plugin boundary would delay the feature and bias the plugin API toward one unusual case. Build it as a first-class service now; it becomes a clean internal reference when the plugin API is designed for real.
- **Not a submodule.** `beat_this_cpp` needs CMake + ONNX Runtime to build and ships an 83 MB model. Treat it as an optional external tool Wombat *locates*, exactly like `ffmpeg` today: resolved via preference → env var → bundled location → `shutil.which`, with graceful degrade when missing.
- **CLI, not the dylib.** Start with the `beat_this_cpp` CLI over subprocess: matches the existing ffmpeg-subprocess approach, gives process isolation (a model crash can't take down the Qt GUI), and has zero build coupling. The `libbeat_this_api.dylib` (tiny API: `BeatThis(model)` / `process_audio`) is a later option only if live progress or skipping the temp-WAV round-trip becomes worthwhile.
- **`.beats` is the serialization format** of the in-memory grid — so import/export and detection feed the exact same path (overlay, snap, snippets).

---

## Data model — `BeatGrid` + `.beats` I/O

In `wombat/audio/beats.py`:

```python
@dataclass(frozen=True)
class BeatGrid:
    times: np.ndarray    # float64 seconds, sorted ascending
    counts: np.ndarray   # int32, 1 = downbeat, 2..N = other beats, 0 = unknown

    @property
    def downbeats(self) -> np.ndarray: ...   # times where count == 1
    def in_span(self, t0, t1) -> "BeatGrid": ...
    def nearest(self, t) -> float | None: ...   # for snap
```

`.beats` is TSV `time<TAB>count` (col1 = seconds, col2 = 1..N; downbeat = 1). Two pure functions:

- `parse_beats(text) -> BeatGrid` — tolerant of blank lines and single-column rows (count defaults to 0/unknown).
- `serialize_beats(grid) -> str`.

Fully headless and unit-testable with no binary.

## Detection service

In `wombat/audio/beats.py`, mirroring `extract_waveform` in `waveform.py`:

```python
def detect_beats(video_path: str) -> BeatGrid | None:
    # cache hit (path + mtime) → return
    # resolve binary + model; missing → return None (graceful degrade)
    # ffmpeg → temp mono WAV (model resamples internally)
    # subprocess: [bin, model, tmp.wav, "--output-beats", tmp.beats]
    # parse_beats(tmp.beats) → BeatGrid; cache; cleanup temps
```

**Tool resolution** (`resolve_beat_tool()`), in order:
1. Preference (`AppSettings.load_beat_binary_path` / `load_beat_model_path`)
2. Env (`WOMBAT_BEAT_THIS_BIN`, `WOMBAT_BEAT_THIS_MODEL`)
3. `shutil.which("beat_this_cpp")`, model next to it (`onnx/beat_this.onnx`)

**Cache:** reuse the waveform `_cache_key`/`_cache_dir` scheme (path + mtime → digest) in a `beats/` subdir, stored as `.npz` (times + counts). Inference is slow, so caching is mandatory. The shared helpers (`_cache_key`, `_cache_dir`, `_ffmpeg_path`) move to `wombat/audio/_cache.py`.

**Testing without the 83 MB model:** point `WOMBAT_BEAT_THIS_BIN` at a fake script that writes a fixed `.beats`. The real-binary path is a separate `skipif`-gated test.

## Background loader

`wombat/audio/beat_loader.py` — a near-verbatim copy of `WaveformLoader` (same slow-background-job shape):
- `beats_ready = Signal(object)` (`BeatGrid | None`)
- optional `detection_started`/`detection_finished` for a status-bar spinner (CLI gives no incremental progress)
- `load(video_path)`, `cancel()`, same QThread lifecycle.

## Settings + preferences

`wombat/settings.py` (existing getter/setter pattern):
- `load/save_beat_binary_path`, `load/save_beat_model_path`
- `load/save_snap_to_beats` (bool)
- `load/save_beats_visible` (bool)

`preferences_dialog.py`: two file-picker rows (binary, model) with browse + "not found" validation, mirroring the ffmpeg-missing UX.

## main_window wiring

Mirror the waveform wiring (`video_loaded` → loader → timeline). Detect only when the tool resolves (no nag otherwise). Store the resulting `BeatGrid` on the editor/session so snap and snippets reach it. Cancel alongside the waveform loader on close. Manual re-detect available via the Beats menu.

## Timeline overlay

In `timeline_widget.py`, copy the waveform plumbing:
- state `_beats: BeatGrid | None`, `_show_beats: bool`; `set_beats`, `set_beats_visible`
- paint vertical ticks at `viewport.time_to_x(t)`, culled via `BeatGrid.in_span`; **downbeats** taller + brighter, other beats short/dim; drawn under action nodes, over the waveform
- View menu "Beat Markers" checkable action next to "Audio Waveform".

## Snap-to-beat

`snap_time_to_beat(t, grid, tolerance_s)` over `BeatGrid.nearest`. In `editor.py`, add beats as a snap source in the placement/drag paths, gated by `snap_to_beats`. When both frame-snap and beat-snap are on: snap to beat first (musical intent), then frame-quantize.

## Snippet integration (high-value piece)

`Rhythm.beats(span, fps) -> np.ndarray` *is* a beat grid. Add to `rhythms.py`:

```python
class DetectedBeats(Rhythm):
    def __init__(self, grid: BeatGrid, downbeats_only: bool = False): ...
    def beats(self, span, fps) -> np.ndarray:
        g = self.grid.in_span(*span)
        return g.downbeats if self.downbeats_only else g.times
```

Composed via the existing `BeatSnippet` (Rhythm × PosAlgorithm), detected beats × any position algorithm produce patterns locked to the music. Register in `library.py`. The grid is session state, not a static param, so the snippet panel receives the active grid from `main_window`; the rhythm is offered only when a grid exists.

## `.beats` import/export

A "Beats" menu: **Import .beats…**, **Export .beats…**, **Detect beats** (manual/re-run). Import/export call `parse_beats`/`serialize_beats` and set the grid on the same path detection uses.

---

## Testing strategy

- **Headless (CI):** `BeatGrid`, `.beats` round-trip, `in_span`/`nearest`, cache read/write, `DetectedBeats.beats`, snap helper.
- **Detection service:** fake-binary script writing a fixed `.beats`; asserts extract → run → parse → cache and the cache-hit short-circuit.
- **Real binary:** one `skipif`-gated integration test for local runs.
- Keep the 83 MB model out of the repo and CI.

## Packaging (later)

For releases, bundle the prebuilt binary + `beat_this.onnx` per platform (macOS arm64, Linux/Win x86-64); `resolve_beat_tool()` checks the bundled location. For dev, point the preference at `../beat_this_cpp/build/beat_this_cpp`.

---

## Commit sequence (one logical change each)

1. **`BeatGrid` + `.beats` I/O + tests** — headless data model.
2. Detection service + cache + tool resolution + tests (fake binary).
3. Loader + settings + preferences + main_window wiring.
4. Timeline beat overlay + view toggle.
5. Snap-to-beat.
6. `DetectedBeats` rhythm + snippet wiring.
7. `.beats` import/export/detect menu.

Steps 1–2 are pure backend and land before any UI. Steps 4–6 are independent and may reorder.
