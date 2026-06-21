"""Invert Layer — the smallest useful Wombat plugin.

Flips every action's position on the active layer (pos → 100 - pos) in one undo
step. Serves as a worked reference for the plugin API: subclass WombatPlugin,
keep the PluginContext from on_load, and mutate through ctx.edit(...).
"""
from __future__ import annotations

from wombat.plugins import PluginContext, WombatPlugin


class InvertLayerPlugin(WombatPlugin):
    def on_load(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        ctx.log.info("Invert Layer ready")

    def invert_active(self) -> None:
        """Invert the positions of every action on the active layer."""
        layer = self.ctx.active_layer
        if layer is None:
            return
        with self.ctx.edit("Invert layer (plugin)", target=layer) as edit:
            for a in layer.actions:
                edit.set_pos(a.at, 100 - a.pos)
