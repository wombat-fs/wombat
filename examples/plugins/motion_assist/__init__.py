"""Motion Assist — the reference Wombat plugin.

End-to-end demonstration of the plugin architecture, modelled on the OFS
MotionVectors / FunscriptToolbox workflow but done the Wombat way:

  * a **command** (and a Generate button) starts the work;
  * the heavy computation runs **off the GUI thread** via ``ctx.run_async`` —
    this is where a real motion plugin would open the video with OpenCV and
    derive strokes from frame-to-frame motion;
  * the result is written to the plugin's **own non-destructive layer** via
    ``ctx.create_layer`` / ``ctx.edit`` (no shadow lists, no clobbering the
    user's actions — the FunscriptToolbox ``virtual_actions`` hack disappears);
  * a **declarative settings panel** re-generates the layer live as parameters
    change, and the layer is found again by its ``plugin_id`` provenance.

The motion analysis here is a dependency-free stand-in (a rhythmic pattern built
with numpy on the worker thread) so the plugin is always runnable; the comment in
:func:`generate_actions` marks exactly where real frame analysis would go.
"""
from __future__ import annotations

from typing import Any

from wombat.plugins import Action, PluginContext, TaskReport, WombatPlugin
from wombat.plugins.ui import (
    Button,
    FloatInput,
    Group,
    IntSlider,
    PanelSpec,
    Text,
)

DEFAULTS: dict[str, Any] = {"amplitude": 80, "period_ms": 500, "span_s": 10.0}


def generate_actions(
    span: tuple[float, float],
    params: dict[str, Any],
    video_path: str | None,
    report: TaskReport,
) -> list[Action] | None:
    """Produce stroke actions for ``span``. Runs on a worker thread.

    Returns None if cancelled. In a real motion plugin this is where you would
    open ``video_path`` with ``cv2.VideoCapture``, read the frames covering the
    span, compute motion magnitude per frame, and map peaks/troughs to positions.
    Here we synthesise a rhythmic top/bottom pattern with numpy instead — the
    threading, cancellation, and progress contract is identical.
    """
    import numpy as np

    start, end = span
    period = max(0.05, float(params["period_ms"]) / 1000.0)
    half = period / 2.0
    amp = max(0, min(100, int(params["amplitude"])))
    lo = 50 - amp // 2
    hi = lo + amp

    times = np.arange(start, end + half, half)
    actions: list[Action] = []
    for i, t in enumerate(times):
        if report.cancelled:
            return None
        if i % 256 == 0:
            report.progress(i / max(1, len(times)), "analysing motion")
        pos = hi if i % 2 == 0 else lo
        actions.append(Action(float(t), int(pos)))
    return actions


class MotionAssistPlugin(WombatPlugin):
    LAYER_NAME = "Motion Assist"

    def on_load(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.cfg: dict[str, Any] = dict(DEFAULTS)
        ctx.register_command(
            "generate",
            "Motion Assist: Generate at playhead",
            self.generate,
            default_key="Ctrl+Shift+M",
        )
        ctx.log.info("Motion Assist ready")

    # ---------------------------------------------------------------- settings

    def settings_panel(self) -> PanelSpec:
        return PanelSpec(
            [
                Text("Generate a motion-derived stroke pattern starting at the playhead."),
                Group(
                    "Pattern",
                    [
                        IntSlider("amplitude", "Amplitude", 0, 100, self.cfg["amplitude"]),
                        IntSlider("period_ms", "Period (ms)", 100, 2000, self.cfg["period_ms"]),
                        FloatInput("span_s", "Span (s)", self.cfg["span_s"], 0.5, 600.0, 0.5, 1),
                    ],
                ),
                Button("regen", "Generate", on_click=self.generate),
            ],
            on_change=self._on_setting_changed,
        )

    def _on_setting_changed(self, key: str, value: object) -> None:
        self.cfg[key] = value
        # Live preview: only regenerate if a layer already exists, so dragging a
        # slider before the first Generate doesn't spawn layers.
        if self._my_layer() is not None:
            self.generate()

    # ----------------------------------------------------------------- generate

    def generate(self) -> None:
        if self.ctx.active_channel is None:
            self.ctx.log.warning("No active channel to generate into")
            return
        start = self.ctx.player.position
        span = (start, start + float(self.cfg["span_s"]))
        params = dict(self.cfg)
        video_path = self.ctx.player.video_path
        self.ctx.run_async(
            lambda report: generate_actions(span, params, video_path, report),
            on_done=lambda actions: self._apply(span, params, actions),
            on_error=lambda exc: self.ctx.log.error("generate failed: %s", exc),
            label="Motion Assist",
        )

    def _apply(self, span: tuple[float, float], params: dict, actions: list[Action] | None) -> None:
        """Write the result to our layer (GUI thread). Reuses the layer if present."""
        if actions is None or self.ctx.active_channel is None:
            return
        layer = self._my_layer()
        if layer is None:
            self.ctx.create_layer(
                self.LAYER_NAME, span=span, actions=actions, params=params
            )
        else:
            with self.ctx.edit(self.LAYER_NAME, target=layer) as edit:
                edit.clear()
                for a in actions:
                    edit.add(a.at, a.pos)

    def _my_layer(self):
        """Find this plugin's layer on the active channel via its provenance stamp."""
        ch = self.ctx.active_channel
        if ch is None:
            return None
        for lv in ch.layers:
            if lv.plugin_id == self.ctx.plugin_id:
                return lv
        return None
