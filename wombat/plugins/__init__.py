"""Native Python plugin system for Wombat.

The equivalent of OFS's Lua extensions, but plain Python — no embedding needed
since the app is already Python. See docs/phase-9-plugin-api.md for the design.

Public surface for plugin authors:
  - WombatPlugin    — base class to subclass
  - PluginContext   — the curated handle into the app, passed to on_load
  - PanelSpec/...    — declarative settings UI (added later)

Host-side:
  - PluginManager   — discover/enable/disable plugins
  - PluginManifest  — parsed plugin.toml metadata
"""
from __future__ import annotations

from wombat.plugins.api import (
    Action,
    ChannelView,
    EditSession,
    LayerView,
    PluginContext,
    TaskHandle,
    TaskReport,
    WombatPlugin,
)
from wombat.plugins.manifest import PLUGIN_API_VERSION, ManifestError, PluginManifest

__all__ = [
    "Action",
    "ChannelView",
    "EditSession",
    "LayerView",
    "ManifestError",
    "PLUGIN_API_VERSION",
    "PluginContext",
    "PluginManifest",
    "TaskHandle",
    "TaskReport",
    "WombatPlugin",
]
