# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Wombat** is a new cross-platform funscript authoring and editing tool being built from scratch. It is not yet implemented — only documentation exists so far. The goal is a viable alternative to OpenFunscripter (OFS) that runs on all major platforms.

See `ROADMAP.md` for the architecture overview, package layout, and the phased build plan. Work proceeds in dependency order; each phase ends with a runnable milestone.

## Tech Stack

- **Python 3** (3.10+ recommended)
- **PySide6** for the GUI (Python Qt bindings)
- **python-mpv** (libmpv) for video playback — chosen over python-vlc for frame-accurate seeking/stepping, which is essential when placing actions against specific video frames. libmpv is cross-platform (Linux/macOS/Windows); it's the same player OFS relies on.

## Platform Targets

- **macOS: Apple Silicon only.** Intel Macs are explicitly out of scope (oldest is now 5+ years old, and Intel-era libmpv was the source of the historical macOS pain). Don't add Intel-specific workarounds.
- **Linux** and **Windows**: supported, x86-64.
- Primary development happens on Apple Silicon macOS.

## Funscript Format

Funscripts are JSON files that synchronize haptic device positions with video playback:

```json
{
  "version": "1.0",
  "inverted": false,
  "range": 90,
  "actions": [
    { "pos": 0, "at": 100 },
    { "pos": 100, "at": 500 }
  ]
}
```

- `at`: timestamp in milliseconds (int)
- `pos`: device position 0–100 (int)
- `inverted`: optional boolean, flips pos values
- `range`: optional, default 0–100

## Planned Architecture

### Channels and Layers

Each project links multiple funscript *channels* to a single video source. Typical channels (names match funscript-tools' axes): `orig`, `alpha`, `beta`, `volume`, `frequency`, `pulse_frequency`, `pulse_width`, `pulse_rise_time`. Each channel has a base funscript plus optional layers. Layers contain action snippets that override lower levels. Wombat synthesizes the layer stack with configurable smooth fade-in/fade-out transitions.

### Snippet Library

Wombat should offer drum-beat patterns for `at` keys with algorithms for `pos` values (alternating, sinusoidal, etc.) as a snippet library.

### Event System

The `config.event_definitions.yml` format from funscript-tools (see `funscript-tools/` reference) defines composite multi-channel events in YAML. Wombat should support loading these YAML files directly. Operations include `apply_modulation` (waveform overlay on an axis), `set_value`, `fade`, etc.

### GUI Layout

- Main widget: video player (via python-mpv / libmpv)
- Below video: channel lanes displayed as affine graphs with nodes at each action, visually similar to video editing timelines
- Each channel shows its layer stack
- Keyboard shortcuts for most commands

## Video Playback (implementation sketch)

This is a good first thing to build — it de-risks the riskiest dependency and gives a foundation the timeline hangs off of. There are two ways to embed libmpv in Qt:

1. **Window embedding (`wid`)** — hand mpv a native window handle and let it render itself. Simplest, but the video becomes an opaque native subwindow: you can't paint Qt widgets (timeline overlays, OSD, selection cursors) on top of it, z-ordering fights Qt, and it's historically the flakiest path on macOS. **Avoid.**
2. **Render API (OpenGL) — use this.** mpv renders into a framebuffer you own inside a `QOpenGLWidget`, so the video composes like any other Qt content and you can draw over it. Portable across Linux/macOS/Windows. python-mpv exposes this via `MpvRenderContext`.

### Skeleton (render API)

```python
import mpv
from PySide6 import QtCore, QtGui
from PySide6.QtOpenGLWidgets import QOpenGLWidget

def _get_proc_address(_ctx, name):
    glctx = QtGui.QOpenGLContext.currentContext()
    if glctx is None:
        return 0
    return int(glctx.getProcAddress(name.decode("utf-8")))

class MpvWidget(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # vo='libmpv' is REQUIRED — tells mpv to use the render API
        # instead of creating its own window. hr-seek makes scrubbing frame-exact.
        self.mpv = mpv.MPV(vo="libmpv", hr_seek="yes", keep_open="yes")
        self._ctx = None

    def initializeGL(self):
        self._ctx = mpv.MpvRenderContext(
            self.mpv, "opengl",
            opengl_init_params={"get_proc_address": _get_proc_address},
        )
        # update_cb fires on mpv's render thread — DO NOT touch GL/Qt here.
        # Marshal to the GUI thread; queued signal -> update() -> paintGL().
        self._ctx.update_cb = lambda: QtCore.QMetaObject.invokeMethod(
            self, "update", QtCore.Qt.QueuedConnection)

    def paintGL(self):
        if not self._ctx:
            return
        ratio = self.devicePixelRatioF()          # Retina-correct sizing
        self._ctx.render(
            flip_y=True,
            opengl_fbo={
                "w": int(self.width() * ratio),
                "h": int(self.height() * ratio),
                "fbo": self.defaultFramebufferObject(),
            },
        )

    def closeEvent(self, ev):
        # Free render context before the MPV/GL context dies.
        if self._ctx: self._ctx.free(); self._ctx = None
        self.mpv.terminate()
        super().closeEvent(ev)
```

### Things that bite

- **Threading:** `update_cb` is called off the GUI thread. Never call OpenGL or Qt from it — only schedule a repaint (queued `update()`). All mpv property reads/commands should happen on the GUI thread too.
- **`vo='libmpv'`** is mandatory for the render API; omitting it makes mpv try to open its own window.
- **Retina/HiDPI:** multiply widget size by `devicePixelRatioF()` for the FBO dimensions, or video renders at quarter-size / wrong scale on macOS.
- **macOS GL:** only OpenGL up to 4.1 (core) is available; libmpv's render API works within that, but request a compatible surface format early (`QSurfaceFormat`) at app startup.
- **A/V sync:** call `self._ctx.report_swap()` after the buffer swap if presentation timing drifts (optional, add if needed).

### Mirror OFS's player abstraction

Wrap mpv behind a clean interface like OFS's `OFS_Videoplayer` (see `OFS/OFS-lib/videoplayer/OFS_Videoplayer.h`). The key idea to copy: track a **logical position** (the last time you *requested* via seek) separately from the player's **actual reported position**, so the timeline cursor stays stable while frame-stepping. Expose frame stepping (mpv commands `frame-step` / `frame-back-step`), exact seeking (`seek <t> absolute+exact`), and speed control. Frame-exact stepping is the whole reason libmpv was chosen — make sure it's wired through.

## Reference Repositories

Both reference repos are **read-only reference material**, not part of Wombat's build.

### `OFS/` — OpenFunscripter (C++)

A feature-complete funscript editor, no longer actively maintained. Use as a UX reference for what features and workflows to support. The codebase is cross-platform-capable (it ships Windows binaries and a Linux AppImage; macOS was untested by the author only for lack of hardware, not a technical barrier). See `OFS/CLAUDE.md` for a full architecture breakdown and a prioritized list of ideas to port. Key reference: `OFS/LuaApiReference.md` for scriptable operations.

### `funscript-tools/` — Restim Funscript Processor (Python/Tkinter)

A batch-processing tool that generates 10 derivative funscripts from a base one. Key things to reuse or integrate:

- **Processing pipeline** in `funscript-tools/processor.py` — generates alpha/beta/frequency/volume/pulse channels from a main funscript
- **1D-to-2D conversion** in `funscript-tools/processing/funscript_1d_to_2d.py` — algorithms: Circular, Top-Left-Right, Top-Right-Left, 0-360
- **Event definitions YAML format** — see `funscript-tools/config.event_definitions.yml` and `funscript-tools/FUNDAMENTAL_OPERATIONS.md` for the full operation spec
- **Motion Axis Generation** — linear interpolation mapping of main funscript to E1–E4 axes via user-defined control point curves

The funscript-tools tech stack uses Tkinter; Wombat uses PySide6 instead. Algorithms can be ported directly; UI code cannot.

## Key Design Decisions from README

- Multi-channel editing with layered overrides (non-destructive)
- Layer transitions are smooth (configurable fade in/out)
- Should import funscript-tools event YAML definitions natively
- AI generation is explicitly out of scope
- Should feel similar to OFS but be cross-platform and actively maintained
