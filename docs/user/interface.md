# The Interface

Wombat's window has three regions: the **video player** on top, the **timeline**
below it, and **docked panels** around them that you can show, hide, drag, and
tab together.

```
┌───────────────────────────────────────────────┬───────────────┐
│                                                │  Channels     │
│                video player                    │  Snippets     │
│                                                │  Events       │
│                                                │  Chapters     │
├───────────────────────────────────────────────┤  Recording    │
│  ◀  ▶  ⏸   00:12.500 / 03:40.000     30 fps    │  (tabbed)     │
├────────────────────────────────────────────────┴──────────────┤
│  time ruler                                                     │
│  ╭─ orig ──────●───────●──────●─────────────────────────────╮   │
│  │             layer lanes…                                  │   │
│  ╰───────────────────────────────────────────────────────────╯  │
└────────────────────────────────────────────────────────────────┘
```

## The video player

Renders the loaded video. Overlays (such as the optional
[device simulator](chapters-and-export.md)) draw on top of it.

## The transport bar

Directly under the video: play/pause, the current time and total duration
(shown as `m:ss.mmm`), the detected frame rate, and a position slider. Playback
controls also work from the keyboard — see
[Keyboard Shortcuts](keyboard-shortcuts.md).

## The timeline

The heart of editing. Each **channel** is drawn as a lane: actions are nodes,
connected by lines, plotted with time on the X axis and position (0–100) on the
Y axis. The active channel is highlighted; others are dimmed.

**Navigation**

- **Scroll** to zoom in and out around the cursor.
- **Drag** an empty part of the ruler/lane to pan.
- The **playhead** tracks playback; the time ruler labels adjust their precision
  as you zoom.
- With the timeline focused, **← / →** jump between adjacent actions (rather than
  stepping frames).

**Layers.** Click the ▶/▼ triangle on a channel to expand its layer stack into
sub-lanes. Layer spans and fade handles can be dragged directly here — see
[Channels & Layers](channels-and-layers.md).

**Optional overlays** (toggle in the **View** menu):

- **Heatmap** — colours the line by stroke speed (blue = slow → red = fast).
- **Audio Waveform** — draws the video's audio under the active channel.
- **Beat Markers** — vertical lines at detected beats (downbeats brighter).

**Right-click** a lane for a context menu to add or remove a chapter at that
point.

## The panels

All of these are dock widgets. Use the **View** menu to toggle any of them, and
drag them to rearrange or tab them together.

| Panel | Purpose | More |
|---|---|---|
| **Channels** | Add/remove channels and manage each one's layer stack. | [Channels & Layers](channels-and-layers.md) |
| **Snippets** | Generate pattern content and insert it as a layer. | [Snippets](snippets.md) |
| **Events** | Load `event_definitions.yml` and apply multi-channel events. | [Events](events.md) |
| **Chapters** | Add, rename, and remove chapter markers. | [Chapters & Export](chapters-and-export.md) |
| **Recording** | A live slider you can record into an axis in real time. | [Editing Actions](editing.md) |

## The menus

- **File** — New/Open project, Open Media, Import Funscript, Save / Save As,
  Export Funscripts, Export Heatmap Image (with or without chapters), Quit.
- **Edit** — Undo/Redo, Cut/Copy/Paste, the **Select** submenu, the **Transform**
  submenu, Delete, Channel Metadata, Preferences.
- **Scripting** — choose the input mode (Default / Alternating / Recording) and
  reset the alternating state.
- **Beats** — Detect Beats, Import `.beats`, Export `.beats`.
- **View** — toggle panels and overlays, Dark Theme, Snap to Frame, Snap to
  Beats.
- **Help** — About.

## Preferences

**Edit ▸ Preferences…** holds app-wide settings such as the dark theme, the
synthesis sampling parameters, and the default **simplify epsilon** used by the
Transform ▸ Simplify command.
