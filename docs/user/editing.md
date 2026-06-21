# Editing Actions

Everything in this page operates on the **active layer** of the **active
channel**. Switch the active channel/layer in the [Channels](channels-and-layers.md)
panel. Every edit is undoable (`Ctrl+Z` / `Ctrl+Y`), and a single undo can span a
multi-channel change.

## Adding actions

With a channel active:

- **Position keys** — move the playhead, then press a key to drop an action at
  that time and position: `` ` ``=0, `1`–`9`=10–90, `0`=100. (These are ignored
  while you're typing in a text field.)
- **Click** an empty part of a channel lane to add a point at that time/position.
- **`P`** drops a point at position 50 at the playhead.

How a keypress is interpreted depends on the active **scripting mode** (below).

### Duplicate protection

Wombat won't let you stack two actions on virtually the same spot. If you add a
point within half a video frame of an existing one, the existing point is
replaced rather than duplicated — so an accidental double-click leaves you with a
single clean action. The same guard applies when you drag a point on top of a
neighbour.

## Selecting

- **Click** a point to select just it.
- **Drag a rubber-band box** over a lane to select every point inside it.
- **Edit ▸ Select ▸ Select All** (`Ctrl+A`).

The **Edit ▸ Select** submenu adds playhead- and shape-aware selections:

| Command | Effect |
|---|---|
| Select Left of Playhead | everything at or before the playhead |
| Select Right of Playhead | everything at or after the playhead |
| Set Selection Start / Set Selection End | mark two times, select the range between them |
| Isolate Action | remove the two neighbours of the action nearest the playhead |
| Top / Middle / Bottom Points Only | narrow the current selection to its peaks / mids / valleys |

`Select Left/Right` default to **Ctrl+Alt+←** and **Ctrl+Alt+→**; the rest are
unbound by default and can be assigned in your
[keybindings](keyboard-shortcuts.md).

## Moving and nudging

- **Drag** a selected point (or selection) to move it in time and position.
- **↑ / ↓** — nudge the selection by one position unit.
- **Shift+← / Shift+→** — nudge the selection's timing by half a frame.
- Press a **position key** while points are selected to set them all to that
  position (instead of inserting a new action).

## Deleting

- **Delete** (or **Backspace**) removes the selected actions.
- **Edit ▸ Select ▸ Isolate Action** clears the clutter around a single point.

## Transforms

**Edit ▸ Transform** reshapes the selection (or the whole layer if nothing is
selected):

| Command | What it does |
|---|---|
| **Invert Positions** | Flips each position within the channel range (e.g. 20 → 80). |
| **Equalize** | Evens out the timing of the selected points between their endpoints. |
| **Simplify** | Removes redundant points with the Ramer–Douglas–Peucker algorithm, keeping the shape. The aggressiveness is the **simplify epsilon** in Preferences. |

A common cleanup is: rubber-band a noisy stretch → **Transform ▸ Simplify** →
fine-tune by hand.

## Snapping

Two snap modes (toggle in the **View** menu) constrain where new and moved
actions land:

- **Snap to Frame** — quantise times to exact video frames. Recommended when you
  want every action on a frame boundary.
- **Snap to Beats** — quantise to detected musical beats (see
  [Audio & Beats](audio-and-beats.md)). When both are on, beats are applied first
  and then rounded to the nearest frame.

## Clipboard

- **Copy** (`Ctrl+C`) / **Cut** (`Ctrl+X`) the selection.
- **Paste** (`Ctrl+V`) drops the copied actions at the playhead.
- **Paste Exact** (`Ctrl+Shift+V`) restores them at their original times.

## Scripting (input) modes

Choose under the **Scripting** menu. The mode decides what "add a point" means:

- **Default** — a position key inserts exactly that position. The straightforward
  way to place points.
- **Alternating** — successive inserts alternate between a high and a low value,
  for quickly laying down up/down strokes. **Reset Alternating** restarts the
  cycle.
- **Recording** — capture motion in real time. Open the **Recording** panel, press
  **● Record**, and drag the vertical slider while the video plays; Wombat samples
  the slider (~30 Hz) straight into the active axis. Press Record again to stop.
  Great for a first rough pass you then clean up with **Transform ▸ Simplify**.
