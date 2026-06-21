# Snippets

A **snippet** generates action content from a pattern instead of you placing every
point by hand. You pick a preset, tune it, preview it, and insert it as a
[layer](channels-and-layers.md). The **Snippets** panel drives this.

## How a snippet is built

Every beat-style snippet combines two parts:

- a **rhythm** that decides *when* actions occur (the `at` times), and
- a **position algorithm** that decides *what* value each one takes (the `pos`).

So "120 BPM" (rhythm) × "alternate 0/100" (position) gives a steady up/down
stroke at 120 beats per minute. A second family, **waveform** snippets, instead
emits a dense continuous curve.

## The preset library

Presets are grouped by category in the panel's dropdown:

| Category | Examples | Idea |
|---|---|---|
| **Beat** | Alternating, Buzz, Slow Pulse, Swing Alternating, Subdivided 16ths | Steady beats at a chosen BPM, alternating between two positions. |
| **Detected** | On Beats, On Downbeats, Throb on Beats | Timing comes from [beat detection](audio-and-beats.md) of the loaded video's audio. |
| **Euclidean** | Pulse Train 3/8, 5/8, 7/16 | Evenly-spread rhythmic patterns (N pulses across M steps). |
| **Tempo** | Tease, Slow Down | Accelerando — the BPM ramps from a start to an end value across the span. |
| **Ramp** | Rising Ramp, Falling Ramp | Beats whose positions climb or fall linearly. |
| **Waveform** | Throb, Sine/Triangle/Square/Sawtooth Wave, High Frequency Sine | Continuous oscillations; the "Wave" presets are dense rather than per-beat. |
| **Layered** | Alternate Over Base, Follow Base | Build on the signal already beneath the layer — add an alternating offset, or resample the underlying motion at beat times. |

The position algorithms behind these include **Alternate** (toggle two values),
**Ramp** (linear sweep), **Sine** (oscillate around a center), **Alternate Over
Base**, and **Follow Base**.

## Inserting a snippet

1. Select a **Preset**; its description appears beneath the dropdown.
2. Tune the exposed **parameters** (BPM, low/high positions, amplitude, etc.).
   The **Preview** updates as you type (debounced).
3. Set the **Span** — a **Start** time and a **Duration** — or click **Use
   selection** to match the current timeline selection's time range.
4. Choose **Layer options**: the **blend mode** (Additive / Override / Multiply)
   and fade-in/out for how the new layer eases in.
5. Click **Insert as Layer**. The snippet is added as a new layer on the active
   channel, inside the span you set, blending per your choice.

Because it lands as a layer, it's fully non-destructive — adjust its span, fades,
or blend afterwards, toggle it on and off, or delete it, without touching what's
underneath.

## Tips

- **Layered** presets (`Alternate Over Base`, `Follow Base`) only make sense over
  existing motion — put them above a base that already has content.
- The **Detected** presets need beats; run **Beats ▸ Detect Beats** first (see
  [Audio & Beats](audio-and-beats.md)).
- Generate a busy waveform, then thin it with **Edit ▸ Transform ▸ Simplify** if
  you want fewer, editable points.
