# Chapters & Export

## Chapters

Chapters are named markers along the timeline — useful for structuring a script
("intro", "build", "finish") and for navigating quickly. The **Chapters** panel
manages them.

- **Add** creates a chapter at the current playhead; you're prompted for a name.
- **Rename** / **Remove** act on the selected chapter.
- **Double-click** a chapter to jump the playhead to it.
- You can also **right-click** the timeline to add or remove a chapter at that
  point.

Chapters can be **points** or **ranges** (with a start and an end). They show on
the timeline and can be burned into an exported [heatmap](#heatmap-images).

**Navigate** between chapters with **`[`** (previous) and **`]`** (next).

## Channel metadata

**Edit ▸ Channel Metadata…** edits the export metadata for the active channel
(the fields the funscript format carries, such as creator/notes and range). This
is per-channel and is written into that channel's exported file.

## Exporting funscripts

**File ▸ Export Funscripts…** flattens every channel's [layer
stack](channels-and-layers.md) to a plain `.funscript` and writes it out. You
choose a destination folder (it defaults next to your media).

Files are named by **convention**, relative to the media file name:

| Channel | Output file (for `clip.mp4`) |
|---|---|
| `orig` / `main` / `script` / *(unnamed)* | `clip.funscript` |
| `alpha` | `clip.alpha.funscript` |
| `volume` | `clip.volume.funscript` |
| *(any other name `X`)* | `clip.X.funscript` |

This is the same multi-axis convention device software expects, so a multi-channel
project drops straight into your player.

> **Project vs. export.** Your `.wombat` project file (saved with `Ctrl+S`) is the
> editable source — it keeps channels, layers, fades, chapters, and applied events
> in lossless seconds. The exported `.funscript` files are the flattened,
> millisecond output for playback. Keep the `.wombat` file to keep editing.

## Heatmap images

A heatmap is the at-a-glance picture of a script's intensity over time — coloured
by stroke speed, blue (slow) through red (fast). Export one as a PNG:

- **File ▸ Export Heatmap Image…** — the bare heatmap strip for the active
  channel.
- **File ▸ Export Heatmap with Chapters…** — the same strip with a labelled
  chapter track beneath it (enabled when the project has chapters).

Duration comes from the loaded video (or the last action if no video is loaded).
These images are handy for thumbnails, previews, or sharing what a script does
without opening it.
