# Phase 3 — Read-only Timeline

**Goal:** render a channel's synthesized actions as a node-and-line graph below the video, with a playhead synced to the player, zoom/pan, and a time ruler. No editing yet — this proves the canvas, the coordinate mapping, the domain model, and the player integration all work together.

**Milestone (definition of done):** open a video plus its `.funscript`, and watch the playhead track across the drawn script as it plays; zoom and pan the timeline; click the ruler to seek. The action graph stays correctly aligned to time at every zoom level.

Depends on Phase 1 (`VideoPlayer`) and Phase 2 (`Channel`/`ActionList`/interpolation).

---

## Decisions (firm defaults)

| Decision | Choice | Rationale |
|---|---|---|
| Rendering | **Custom `QWidget` + `QPainter`**, culling to the visible time window | A `QGraphicsItem` per action dies at 100k actions. Immediate-mode painting of only the visible slice mirrors OFS and scales. Leave the door open to a `QOpenGLWidget` repaint backend if profiling later demands it. |
| Visible-range culling | via `ActionList.index_range(t0, t1)` (Phase 2) | Draw only on-screen actions, plus one neighbor each side so entering/exiting line segments are correct. |
| Lane model | render a **list of lanes**, one channel each — Phase 3 has exactly one | Structures the widget so Phase 5 (multi-channel) just adds lanes; no rewrite. |
| What's drawn | **`Channel.synthesize()` output**, always | Reinforces the editing/rendering seam. In Phase 3 that's the single base layer. |
| Playhead source | `position_changed` while playing; `logical_time` while the user scrubs | The logical-vs-actual split from Phase 1 — keeps the cursor stable during frame-stepping. |
| Coordinate math | a **pure, Qt-free `Viewport` helper** | Unit-testable without a display, and reused verbatim by Phase 4 hit-testing. |

---

## Package additions

```
wombat/ui/
  timeline/
    __init__.py
    viewport.py      # Viewport — pure time/pos <-> pixel mapping (no Qt)
    timeline_widget.py  # TimelineWidget(QWidget) — paint, zoom/pan, ruler, playhead
    heatmap.py       # optional: speed->color gradient for line segments
wombat/app/
  session.py         # minimal current-document holder (player + channels); Phase 5 -> Project
tests/
  test_viewport.py
```

`session.py` is a deliberately small placeholder: it holds the `VideoPlayer` and the list of open `Channel`s so `MainWindow` and the timeline share state. **Phase 5 formalizes it into `Project`** — keep it thin.

Optional dev dep: `pytest-qt` (for widget-instantiation smoke tests).

---

## `viewport.py` — the coordinate mapping (pure, no Qt)

The heart of the canvas. Time runs left→right; position runs bottom(0)→top(100), matching funscript convention (pos 100 = fully up).

```python
@dataclass
class Viewport:
    offset: float        # seconds at the left edge of the canvas
    visible_time: float  # seconds spanned across the canvas width
    width: int           # canvas pixel width
    lane_top: int        # lane rect top (px)
    lane_height: int     # lane rect height (px)

    MIN_VISIBLE = 1.0      # seconds (max zoom-in)
    MAX_VISIBLE = 300.0    # seconds (max zoom-out)

    def time_to_x(self, t: float) -> float: ...      # (t - offset)/visible_time * width
    def x_to_time(self, x: float) -> float: ...
    def pos_to_y(self, pos: float) -> float: ...     # lane_top + (1 - pos/100)*lane_height
    def y_to_pos(self, y: float) -> float: ...

    def zoom(self, factor: float, anchor_x: float) -> "Viewport": ...
        # change visible_time (clamped MIN/MAX), keeping the time under anchor_x fixed
    def pan(self, dx_seconds: float) -> "Viewport": ...
    def time_window(self) -> tuple[float, float]: ...   # (offset, offset + visible_time)
```

`zoom` anchored at the cursor is what makes Ctrl+scroll feel right. All of this is testable with plain asserts.

---

## `timeline_widget.py` — `TimelineWidget(QWidget)`

State:
- `channels: list[Channel]`, `active_index: int`
- `viewport: Viewport`
- `playhead_time: float`
- `follow_playhead: bool` (auto-scroll while playing; suspended during manual pan)
- `follow_fraction: float = 0.5` (where the playhead sits when following — centered)
- `show_heatmap: bool` (optional feature)

### Painting (`paintEvent`)

Layout: a **ruler strip** along the top, then the **lane area** below (one lane in Phase 3, filling the height). Draw order:

1. **Ruler** (`_draw_ruler`): adaptive time ticks with `mm:ss(.mmm)` labels. Tick density chosen from `visible_time` (e.g. pick a "nice" interval: 0.1/0.5/1/5/10/30/60 s so ~5–10 labels fit). Ruler is also the click-to-seek target.
2. **Per lane** (`_draw_lane`, takes the lane rect + channel + `is_active`):
   - `_draw_height_lines`: faint horizontal guides at pos 0/25/50/75/100.
   - `_draw_lines`: straight segments between consecutive actions (linear interpolation = true semantics). Use `index_range` for the visible slice **plus one action each side** so edge segments are drawn. Active lane full-opacity; inactive lanes dimmed (foreshadows Phase 5).
   - `_draw_points`: a small filled circle at each visible action.
   - `_draw_label`: channel name in a corner.
   - Optional `_draw_heatmap`: color line segments by speed (see below) instead of a flat line color.
3. **Playhead** (`_draw_playhead`): a vertical line at `time_to_x(playhead_time)`, drawn last so it's on top.

Only the visible window is ever drawn, so cost is bounded by what's on screen, not script length.

### Interactions

- **Ctrl + wheel** → `viewport.zoom(factor, cursor_x)` → `update()`.
- **Wheel** (or middle-drag) → `viewport.pan(...)`; sets `follow_playhead = False` so manual navigation isn't fought by auto-scroll (re-enabled when playback starts or via a "follow" toggle/keybind).
- **Click on ruler** → `player.seek_exact(viewport.x_to_time(x))`. (Clicking in the lane area is reserved for Phase 4 editing — no-op for now, or also seeks; pick seek-only to keep it read-only.)
- **Resize** → update `viewport.width`/lane rect, repaint.

### Playhead follow

While playing, on each `position_changed(t)`: set `playhead_time = t`; if `follow_playhead`, set `viewport.offset = t - visible_time * follow_fraction` and repaint. While paused/scrubbing, read `player.logical_time` for the playhead and don't auto-scroll.

---

## Heatmap (optional / stretch — spec so it can be deferred cleanly)

Port OFS's idea: color each line segment by stroke **speed**.

- `speed = abs(pos2 - pos1) / (t2 - t1)` in pos-units per second.
- Cap at `MAX_SPEED = 400.0` (OFS's `MaxSpeedPerSecond`).
- Map `speed/MAX_SPEED` ∈ [0,1] through a gradient (blue → cyan → green → yellow → red).
- `_draw_heatmap` colors each segment accordingly; toggled by `show_heatmap`.

`heatmap.py` exposes a pure `speed_color(speed: float) -> QColor` (the gradient stops are pure data; only the `QColor` construction needs Qt). Keep the gradient table testable.

---

## Wiring into the app

- `MainWindow` owns the `Session` (player + channels). **File ▸ Open Funscript…** loads a file via `load_funscript` → `Channel.from_funscript(fs, name)` → adds to the session → hands the channel list to the timeline. Optionally auto-load a same-basename `.funscript` when opening media (full multi-axis auto-load is Phase 5).
- Connect `player.position_changed` → timeline playhead update; timeline ruler-click → `player.seek_exact`.
- Place `TimelineWidget` in the bottom dock created in Phase 0.

---

## Testing

- **`Viewport` (pure, thorough):** `time_to_x`/`x_to_time` and `pos_to_y`/`y_to_pos` are inverses; `zoom` keeps the anchor time fixed and clamps to MIN/MAX_VISIBLE; `pan` shifts the window; `time_window` correct. Boundary cases (zero-width guard, t at edges).
- **Heatmap (if built):** `speed_color` monotonic mapping; clamps at/above MAX_SPEED; endpoints hit expected colors.
- **Widget smoke (optional, pytest-qt):** instantiate `TimelineWidget`, feed a small channel, call `repaint`/`grab()` without exceptions; simulate a ruler click and assert a seek was requested (mock player).
- **Manual:** the acceptance criteria below.

---

## Acceptance criteria

1. Open a video + its `.funscript`; the action graph draws below the video, time-aligned.
2. Playing the video moves the playhead smoothly across the graph; with follow on, the view scrolls to keep it centered.
3. Ctrl+scroll zooms around the cursor; the graph stays correctly aligned (an action under the cursor stays put). Scroll/middle-drag pans.
4. Clicking the ruler seeks the video to that time.
5. A long script (~100k actions) pans/zooms without noticeable lag (culling works).
6. `Viewport` tests pass; `ruff`/`mypy` clean on new code.

## Task checklist for the implementer

- [ ] `viewport.py` — pure `Viewport` mapping + zoom/pan, fully unit-tested
- [ ] `session.py` — minimal player+channels holder
- [ ] `timeline_widget.py` — paint (ruler, height lines, lines, points, label, playhead), culling via `index_range`
- [ ] Zoom (Ctrl+wheel, cursor-anchored), pan, ruler click-to-seek
- [ ] Playhead follow logic (logical vs actual position)
- [ ] `MainWindow` wiring: Open Funscript…, timeline in bottom dock, player↔timeline signals
- [ ] Heatmap (optional) — `heatmap.py` + `_draw_heatmap` + toggle
- [ ] `test_viewport.py` (+ optional pytest-qt smoke)
- [ ] Verify acceptance criteria on Apple Silicon macOS
```
