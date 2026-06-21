# Quick Start

This guide takes you from a fresh install to an exported funscript.

## 1. Install libmpv

Wombat plays video through **libmpv**, which must be present on your system
*before* you launch the app.

| Platform | Command |
|---|---|
| **macOS (Apple Silicon)** | `brew install mpv` |
| **Linux (Debian/Ubuntu)** | `sudo apt install libmpv2` (or `libmpv-dev`) |
| **Windows** | Download `libmpv-2.dll` and put it on the DLL search path (e.g. next to the executable) |

> **macOS troubleshooting:** if Wombat can't find libmpv, set
> `MPV_DYLIB_PATH=/opt/homebrew/lib/libmpv.dylib` in your environment.

## 2. Install and launch Wombat

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies and run
uv sync
uv run wombat
```

You should see the Wombat window: a large video area with an empty timeline
beneath it and several docked panels around the edges.

## 3. Open a video

**File ▸ Open Media…** (`Ctrl+Shift+O`) and pick a video file. If a funscript
sits next to it with a matching name (e.g. `clip.mp4` and `clip.funscript`),
Wombat loads it automatically into a channel. Sibling axis files such as
`clip.alpha.funscript` are picked up too.

To bring in a script by hand, use **File ▸ Import Funscript…**.

## 4. Play and navigate

- **Space** — play / pause.
- **← / →** — step one frame back / forward (frame-accurate).
- **Ctrl+← / Ctrl+→** — seek 5 seconds.
- Drag the timeline to pan; scroll to zoom (see [The Interface](interface.md)).

Frame-accurate stepping is the whole point of placing actions against specific
frames — use it liberally.

## 5. Create your first actions

If your project has no channel yet, add one in the **Channels** panel (see
[Channels & Layers](channels-and-layers.md)). With a channel active:

- Move the playhead to a frame, then press a **position key** to drop an action
  there:

  | Key | Position | Key | Position |
  |---|---|---|---|
  | `` ` `` | 0 | `5` | 50 |
  | `1` | 10 | `6` | 60 |
  | `2` | 20 | `7` | 70 |
  | `3` | 30 | `8` | 80 |
  | `4` | 40 | `9` | 90 |
  |  |  | `0` | 100 |

- Or **left-click** an empty spot in the channel lane to add a point there.
- Or press **`P`** to drop a point at position 50 at the playhead.

Build a stroke by stepping forward a few frames and dropping the next point. The
timeline draws a line between consecutive actions.

## 6. Refine

- **Click** a point to select it; **drag** to move it.
- **Drag a rubber-band box** across the lane to select many points.
- **↑ / ↓** nudge the selected points by one position unit; **Shift+← / Shift+→**
  nudge their timing by half a frame.
- **Delete** removes the selection; **Ctrl+Z** undoes.

See [Editing Actions](editing.md) for selection tools and transforms (invert,
simplify, equalize).

## 7. Save and export

- **Save Project** (`Ctrl+S`) writes a `.wombat` file. This is your editable
  project — it keeps every channel and layer intact, in lossless seconds.
- **File ▸ Export Funscripts…** writes the flattened `.funscript` file(s) your
  device software reads. Multiple channels are named by convention
  (`clip.funscript`, `clip.alpha.funscript`, …). See
  [Chapters & Export](chapters-and-export.md).

That's the full loop. From here, the [advanced features](README.md#advanced-features)
— layers, snippets, events, and beat detection — are what make Wombat more than a
point editor.
