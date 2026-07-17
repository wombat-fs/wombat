# Phase 1 — Prove Video

**Goal:** frame-accurate video playback embedded in the Qt window, behind a clean `VideoPlayer` abstraction the rest of the app will depend on. This phase de-risks the dependency we deliberately chose libmpv for.

**Milestone (definition of done):** load a video file into the main window, play/pause it, scrub with a seek bar, and step **one frame at a time** forward and backward with visible single-frame accuracy — verified on Apple Silicon macOS. (Intel macOS is explicitly out of scope — see `CLAUDE.md` platform targets.)

Builds on Phase 0 (the surface format and locale are already set in `bootstrap()`).

---

## What this phase delivers

1. `playback/player.py` — `VideoPlayer`, the control/state API + Qt signals (owns the `mpv.MPV` handle).
2. `ui/mpv_widget.py` — `MpvWidget(QOpenGLWidget)`, display only, using libmpv's render API.
3. `ui/transport.py` — transport bar (play/pause, seek bar, frame-step, time/fps readout, speed).
4. Wiring in `MainWindow`: mpv widget as the central video area, transport docked beneath it, **File ▸ Open Media…** loads a video.

New runtime dep is already present from Phase 0 (`python-mpv`). New package: `playback/`.

---

## The `VideoPlayer` interface (the seam — design this carefully)

The rest of Wombat talks to playback **only** through this. Mirror OFS's `OFS_Videoplayer` (`../wombat-reference/OFS/OFS-lib/videoplayer/OFS_Videoplayer.h`). It owns the `mpv.MPV` instance; `MpvWidget` is handed the handle for rendering.

```python
class VideoPlayer(QObject):
    # --- signals (all emitted on the GUI thread) ---
    video_loaded      = Signal(str)      # path
    duration_changed  = Signal(float)    # seconds
    position_changed  = Signal(float)    # seconds (actual, player-reported)
    playback_changed  = Signal(bool)     # is_paused
    speed_changed     = Signal(float)
    end_reached       = Signal()

    def __init__(self) -> None: ...

    # lifecycle
    def load(self, path: str) -> None: ...
    def close_video(self) -> None: ...
    def shutdown(self) -> None: ...        # terminate mpv cleanly

    # transport
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def toggle_play(self) -> None: ...
    def set_paused(self, paused: bool) -> None: ...

    # seeking — all exact/hr-seek
    def seek_exact(self, seconds: float) -> None: ...   # absolute
    def seek_relative(self, seconds: float) -> None: ...
    def seek_percent(self, fraction: float) -> None: ...  # 0..1
    def step_frame(self, forward: bool = True) -> None: ...

    # rate / audio
    def set_speed(self, speed: float) -> None: ...
    def set_volume(self, volume: float) -> None: ...   # 0..100
    def mute(self) -> None: ...
    def unmute(self) -> None: ...

    # --- read-only state ---
    @property
    def logical_time(self) -> float: ...   # last requested seek target (see below)
    @property
    def actual_time(self) -> float: ...    # player-reported time-pos
    @property
    def duration(self) -> float: ...
    @property
    def fps(self) -> float: ...
    @property
    def frame_time(self) -> float: ...     # 1/fps
    @property
    def is_paused(self) -> bool: ...
    @property
    def is_loaded(self) -> bool: ...
    @property
    def video_size(self) -> tuple[int, int]: ...
    @property
    def speed(self) -> float: ...
```

### Logical vs actual position (port this from OFS)

Keep **two** notions of "where we are":

- **`actual_time`** — what mpv reports via the `time-pos` property. Lags a frame or two behind a seek and can jitter.
- **`logical_time`** — the time we last *requested* (via any seek / frame-step). Set it **immediately and synchronously** when a seek is issued.

Rule: while **scrubbing or frame-stepping**, the timeline cursor (Phase 3) reads `logical_time` so it sits exactly where the user put it, with no jitter. While **playing**, `logical_time` follows `actual_time`. This is what makes frame-stepping feel precise instead of rubber-banding. Implement the bookkeeping here in Phase 1 even though the consumer (the timeline) doesn't exist yet.

---

## `MpvWidget` — render API (display only)

Start from the skeleton in the repo `CLAUDE.md` ("Video Playback (implementation sketch)"). Key points, expanded:

- It is **given** the `mpv.MPV` handle by `VideoPlayer`; it does not create or control playback. It only creates the `MpvRenderContext` in `initializeGL` and renders in `paintGL`.
- `mpv.MPV(...)` must be constructed with **`vo="libmpv"`** (done in `VideoPlayer.__init__`), or mpv tries to open its own window and the render API won't work.
- `update_cb` fires on **mpv's render thread** — never call GL/Qt from it. Marshal to the GUI thread with a queued `QMetaObject.invokeMethod(self, "update", Qt.QueuedConnection)`.
- `paintGL` renders into `self.defaultFramebufferObject()` sized by `width*devicePixelRatioF()` × `height*devicePixelRatioF()` with `flip_y=True`.
- Teardown order matters: free the `MpvRenderContext` **before** the GL context / mpv handle is destroyed. Free the render context in the widget; `VideoPlayer.shutdown()` terminates mpv afterward.
- `get_proc_address` bridges to Qt: `int(QOpenGLContext.currentContext().getProcAddress(name.decode()))`. **Version gotcha:** `getProcAddress`'s return type has varied across PySide6 releases (int vs `voidptr`); if you get a type error, adapt the cast. Verify on the actual installed PySide6.

---

## mpv specifics (python-mpv)

- **Construct:** `mpv.MPV(vo="libmpv", hr_seek="yes", keep_open="yes")`. `hr_seek=yes` makes ordinary seeks frame-exact; `keep_open=yes` prevents auto-close at EOF so the last frame stays visible.
- **Observe properties** (via `@player.property_observer("name")` or `observe_property`) and re-emit as Qt signals — **on the GUI thread** (the observer callback runs on mpv's event thread, so marshal with a queued signal):
  - `time-pos` → `position_changed`
  - `duration` → `duration_changed`
  - `pause` → `playback_changed`
  - `speed` → `speed_changed`
  - `eof-reached` → `end_reached`
- **Frame step:** `player.command("frame-step")` / `player.command("frame-back-step")`. After stepping, set `logical_time` from the resulting `time-pos`.
- **Exact seek:** `player.command("seek", seconds, "absolute+exact")`. Set `logical_time = seconds` immediately.
- **fps:** read `container-fps` (fall back to `estimated-vf-fps` if absent/zero). `frame_time = 1/fps`. Guard against zero/None before a video is loaded.
- **video size:** `width` / `height` properties (or `dwidth`/`dheight` for display size).
- **load:** `player.play(path)` or `player.command("loadfile", path)`.

> All property reads and commands should happen on the GUI thread. Don't call into mpv from observer callbacks; just schedule a signal emit.

---

## Transport bar (`ui/transport.py`)

A `QWidget` driven by, and driving, `VideoPlayer`:

- **Play/Pause** button → `toggle_play()`; reflects `playback_changed`.
- **Seek bar** (`QSlider`) spanning 0..duration. Dragging → `seek_exact()`. Update its position from `position_changed`, but **suppress feedback loops** while the user is dragging (don't move the slider from `position_changed` mid-drag).
- **Frame-step** buttons ◀| |▶ → `step_frame(forward=False/True)`.
- **Time readout:** `current / duration` (mm:ss.mmm) and an fps label.
- **Speed** control (combo or small slider) → `set_speed()`.

These map naturally to later keyboard shortcuts (space = play/pause, ←/→ = frame step) — wire those here if cheap, or defer to Phase 9.

---

## Gotchas checklist (most failures will be one of these)

- [ ] `locale.setlocale(LC_NUMERIC, "C")` set at startup (Phase 0) — else mpv misparses floats.
- [ ] `QSurfaceFormat` core 3.3 set before QApplication (Phase 0).
- [ ] `mpv.MPV(vo="libmpv")` — mandatory for the render API.
- [ ] `update_cb` only schedules a repaint; no GL/Qt calls off-thread.
- [ ] Property observers marshal to the GUI thread before touching widgets.
- [ ] FBO sized by `devicePixelRatioF()` (Retina) — else quarter-size/misscaled video on macOS.
- [ ] Render context freed before mpv/GL teardown.
- [ ] macOS: if libmpv isn't found at runtime, set `MPV_DYLIB_PATH` to the Homebrew dylib.
- [ ] `getProcAddress` return-type cast verified against the installed PySide6.

---

## Acceptance criteria

**Manual (primary — GL/video is hard to assert in CI):**
1. **File ▸ Open Media…** loads a video; first frame displays.
2. Play/pause works; seek bar tracks playback and scrubs.
3. Frame-step forward/back advances exactly one frame each press (verify on content with a frame counter or visible motion).
4. Speed control changes playback rate.
5. Resizing the window keeps the video correctly scaled (no Retina mis-scale).
6. Closing the window/app terminates mpv with no crash or hang.

**Automated (minimal, what's feasible headless):**
7. A test that constructs `VideoPlayer`, asserts initial state (`is_loaded` False, sane defaults), and exercises the `logical_time` bookkeeping logic — mock or guard the mpv handle so the test runs without a display. Don't attempt to test actual rendering.

## Task checklist for the implementer

- [ ] `playback/__init__.py`, `playback/player.py` — `VideoPlayer` with the full interface above
- [ ] Property observers → GUI-thread-marshaled Qt signals
- [ ] Logical-vs-actual position bookkeeping
- [ ] `ui/mpv_widget.py` — `MpvWidget` render-API display, correct teardown
- [ ] `ui/transport.py` — transport bar wired both directions
- [ ] `MainWindow`: mpv widget as central video area, transport docked below, **Open Media…** action
- [ ] Frame-step / play-pause keyboard shortcuts (optional)
- [ ] Minimal automated test for `VideoPlayer` state/logical-time
- [ ] Walk the gotchas checklist
- [ ] Verify all manual acceptance criteria on Apple Silicon macOS
