# Channels & Layers

This is Wombat's defining feature. Where most editors give you one flat list of
actions per axis, Wombat gives every channel a **stack of layers** that are
synthesised — with smooth fades — into the final script. Your edits are
non-destructive: you shape layers, and Wombat folds them down.

## Channels

A **channel** is one funscript axis linked to the video. A project can hold many
channels driving the same video. The **Channels** panel manages them.

**Preset names** (offered when you add a channel): `orig`, `alpha`, `beta`,
`volume`, `frequency`, `pulse_frequency`, `pulse_width`, `pulse_rise_time`. These
match [funscript-tools](https://github.com/edger477/funscript-tools)' axis names,
so its event YAMLs and generated files line up with your channels directly. You
can also type a custom name.

The active channel is the one you're editing; it's highlighted in the timeline
while the others are dimmed. On export, each channel becomes its own
`.funscript` file by [naming convention](chapters-and-export.md).

## Layers

Inside a channel, layers are stacked with **layer 0 = the base**. Layers above
the base override or combine with what's beneath them, only within their own time
span, and fade in and out at the edges. Editing always targets the **active
layer** — lower layers stay untouched.

Each layer carries an **envelope**:

- **Enabled** — toggle the layer in or out of the result.
- **Span** — the time window `[start, end]` where the layer is active. A layer
  with no span covers the whole timeline.
- **Fade in / Fade out** — durations over which the layer blends in and out at the
  span edges, so transitions are smooth rather than abrupt.
- **Fade curve** — the shape of those fades.
- **Blend mode** — how the layer combines with the layers below (see next).
- **Center** — the pivot value used by the Additive and Multiply blend modes.

### Blend modes

| Mode | Effect |
|---|---|
| **Override** | The layer replaces what's beneath it inside its span; the fades cross-fade between the lower result and this layer. |
| **Additive** | The layer's value is added as an offset around its **center** (e.g. center 50 → values above 50 push up, below 50 pull down). |
| **Multiply** | The layer scales the signal beneath it, pivoting on its **center** — useful for swelling or damping an existing motion. |

In the timeline, expanded layers show a small badge — `OVR`, `ADD`, or `MUL`.

## Working with layers

Expand a channel (the ▶/▼ triangle, in the timeline or the Channels panel) to see
its layer sub-lanes. From the **Channels** panel you can:

- **Add Layer**, **Duplicate Layer**, **Remove Layer** (the base can't be
  removed).
- **Merge Down** — flatten a layer into the one beneath it; the two become a
  single layer (the image-editor "merge down"). Right-click a layer to find it.
- **Reorder** layers up/down. The panel lists the stack **top-first** (the
  topmost, last-applied override at the top; the base at the bottom), so moving a
  layer **up** gives it higher priority over those below it.
- **Rename** a channel or layer (double-click).
- **Right-click** a layer for its **Blend mode** picker and other options.

Directly on the timeline you can **drag a layer's span edges** to move/resize its
active window, and **drag its fade handles** to set fade-in/out durations — just
like trimming clips and crossfades in a video editor.

## Synthesis

Whatever you see consumed downstream — playback, the heatmap, export — is the
**synthesised** result: Wombat folds the stack from the base upward, applying each
layer's blend and fades, into one flat action list per channel. With a single
base layer this is an identity (the script is exactly your base). Add a layer and
the result updates live.

The sampling detail used when folding continuous layers is configurable under
**Edit ▸ Preferences** (synthesis parameters); the defaults are fine for normal
use.

## A typical layered workflow

1. Author or import your **base** motion on layer 0.
2. **Add a layer** over a section you want to embellish — say a faster passage.
3. Drop a [snippet](snippets.md) into it, or hand-edit its actions.
4. Set its **blend mode** (Additive to ride on top of the base, Override to
   replace it) and pull out the **fades** so it eases in and out.
5. Toggle the layer on/off to compare. Nothing you do here damages the base — flatten
   only happens at export.
