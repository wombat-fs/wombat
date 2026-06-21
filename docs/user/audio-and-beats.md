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

Detected beats power three things:

- **Beat markers** — toggle **View ▸ Beat Markers** to draw a vertical line at
  each beat on the timeline; downbeats (bar starts) are drawn brighter.
- **Snap to Beats** — toggle **View ▸ Snap to Beats** so new and moved actions
  land on beats. With **Snap to Frame** also on, Wombat snaps to the beat first
  and then to the nearest frame.
- **Detected snippets** — the *Detected* category in the [Snippets](snippets.md)
  panel (On Beats, On Downbeats, Throb on Beats) takes its timing from the
  detected grid.

> **Requirement:** beat detection relies on an external `beat_this_cpp` binary
> being installed and locatable on your machine. If detection is unavailable,
> Wombat looks for it like it looks for ffmpeg (a configured path, the
> `WOMBAT_BEAT_THIS_BIN` environment variable, or your `PATH`).

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
