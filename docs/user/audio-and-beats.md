# Audio & Beats

Wombat can show you the video's audio and detect its musical beats, so you can
place actions in time with the sound.

## Audio waveform

Toggle **View ▸ Audio Waveform** to draw the loaded video's audio under the
active channel. Wombat extracts the waveform in the background the first time a
video loads, so it may appear a moment after the video does. It's a visual guide
only — useful for lining up strokes with audible hits.

## Beat detection

**Beats ▸ Detect Beats** analyses the loaded video's audio and produces a grid of
beat times (with downbeats marked). This is an AI-based detection step and runs
**only when you ask for it** — it is deliberately *not* triggered automatically on
video load, because the analysis is heavy.

Detection is an **optional feature** that depends on external tools you install
yourself — see [Setting up beat detection](#setting-up-beat-detection) below. If
those tools aren't configured, everything else in Wombat works normally; you can
still [import a `.beats` file](#importing-and-exporting-beats) produced elsewhere.

Detected beats power three things:

- **Beat markers** — toggle **View ▸ Beat Markers** to draw a vertical line at
  each beat on the timeline; downbeats (bar starts) are drawn brighter.
- **Snap to Beats** — toggle **View ▸ Snap to Beats** so new and moved actions
  land on beats. With **Snap to Frame** also on, Wombat snaps to the beat first
  and then to the nearest frame.
- **Detected snippets** — the *Detected* category in the [Snippets](snippets.md)
  panel (On Beats, On Downbeats, Throb on Beats) takes its timing from the
  detected grid.

## Setting up beat detection

Beat detection is **not built in** — it shells out to an external tool that
Wombat locates on your machine. You need three pieces:

1. **The `beat_this_cpp` binary** — the detector itself. Wombat does not ship it;
   build it from [github.com/mosynthkey/beat_this_cpp](https://github.com/mosynthkey/beat_this_cpp)
   (CMake + ONNX Runtime), or drop in a prebuilt binary if you have one.
2. **The `beat_this.onnx` model** (~83 MB) — the neural-network weights the binary
   runs. It comes with `beat_this_cpp`. If it sits next to the binary (as
   `beat_this.onnx`, or under an `onnx/` folder beside it), Wombat finds it
   automatically and you can leave the model path blank.
3. **ffmpeg** — used to decode the video's audio before analysis, the same way
   Wombat already uses it for the waveform. It must be on your `PATH`.

### Pointing Wombat at the binary

Set the paths in **Preferences ▸ Beat Detection**:

- **Detector binary** — the `beat_this_cpp` executable.
- **ONNX model** — the `beat_this.onnx` file. Leave blank to auto-detect it next
  to the binary.

The dialog shows a live status line telling you whether the binary and model
resolved, so you can confirm the setup before closing it.

Prefer the environment instead? Wombat also reads:

- `WOMBAT_BEAT_THIS_BIN` — path to the binary
- `WOMBAT_BEAT_THIS_MODEL` — path to the ONNX model

For each of the binary and the model, Wombat resolves the first that works, in
order: the Preferences value → the environment variable → (binary) whatever is on
your `PATH` as `beat_this_cpp` / (model) a file found next to the binary. If it
can't resolve both, **Detect Beats** logs a message and does nothing rather than
failing loudly.

## Importing and exporting beats

- **Beats ▸ Import `.beats`…** loads a beat grid from a `.beats` file instead of
  detecting one — handy if you analysed the track elsewhere or want to reuse a
  grid.
- **Beats ▸ Export `.beats`…** saves the current grid so you can keep or share it.

A practical pattern: detect once, **export** the `.beats` file next to your
video, and **import** it next session to skip re-running the analysis.

## A beat-driven workflow

1. Load the video, **Beats ▸ Detect Beats**.
2. Turn on **View ▸ Beat Markers** to see the grid.
3. Either turn on **Snap to Beats** and hand-place strokes that lock to the beat,
   or drop an **On Beats** / **On Downbeats** snippet to fill a section
   automatically.
4. Refine by hand and [export](chapters-and-export.md).
