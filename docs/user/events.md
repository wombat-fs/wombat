# Events

An **event** is a reusable, multi-channel action: one trigger that writes
coordinated content across several axes at once (for example, swelling `volume`
while shifting `frequency` and adding a `pulse`). Wombat reads the same
`event_definitions.yml` format used by
[funscript-tools](https://github.com/edger477/funscript-tools), so definitions
from that ecosystem work directly. The **Events** panel drives this.

## Loading definitions

1. Wombat starts with a **default library** loaded (funscript-tools'
   `config.event_definitions.yml`, bundled under MIT). To use your own, click
   **Load event definitions…** and choose a YAML file.
2. The events in the file are listed, grouped by their headers.

The YAML defines each event as a set of operations on named channels —
`apply_modulation` (overlay a waveform on an axis), `set_value`, `fade`, and so
on. Because Wombat's [channel presets](channels-and-layers.md) use the same names
as funscript-tools (`volume`, `frequency`, `pulse_frequency`, `pulse_width`, …),
the axes in the file map straight onto your channels. Give a channel the matching
name and that axis's content lands there; axes with no matching channel are
skipped with a warning.

## Applying an event

1. Select an event from the list.
2. Set the **Start time** (timecode or seconds — it accepts both). When the
   playhead moves it pre-fills with the current position, so you can scrub to a
   spot and apply there.
3. Optionally adjust the **parameter overrides** shown for that event — each
   exposed parameter gets its own field; leave it at 0 to use the event's
   default.
4. Click **Apply event**.

Wombat translates the event into content on each affected channel and inserts it
as **event layers** — non-destructively, the same way [snippets](snippets.md)
land as layers.

## Re-editing an applied event

Applied events stay editable. Because each one is recorded with its name, group,
start time, and any parameter overrides, you can select it again, change the
start time or parameters, and **update** it in place — or **Cancel update** to
back out. The event layers it created are rewritten to match. This metadata is
saved with your `.wombat` project, so events survive save/reload.

## When to use events vs snippets

- Reach for a **[snippet](snippets.md)** to shape a single channel with a rhythmic
  or waveform pattern.
- Reach for an **event** when one gesture should coordinate *several* channels at
  once according to a definition you (or the funscript-tools community) have
  written.
