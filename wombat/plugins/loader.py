"""PluginManager — discover, import, enable/disable plugins with error isolation.

Plugins are imported into the host process (no separate VM — Python has no cheap
equivalent of Lua's per-extension VM, and the value isn't worth subprocess
overhead). Isolation is by error-boundary, not by sandbox: every call into plugin
code is wrapped so an exception is logged and the plugin is flagged ``errored``
rather than crashing Wombat.

Security posture (v1): a plugin is arbitrary Python with full process privileges —
the same trust model as OFS Lua extensions. Installing a plugin means running its
code. See docs/phase-9-plugin-api.md.
"""
from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from wombat.plugins.api import PluginContext, WombatPlugin
from wombat.plugins.manifest import (
    PLUGIN_API_VERSION,
    ManifestError,
    PluginManifest,
    discover_with_errors,
)

log = logging.getLogger(__name__)

# A factory the host supplies to mint a PluginContext for a given plugin id.
ContextFactory = Callable[[PluginManifest], PluginContext]


class PluginState(str, Enum):
    DISCOVERED = "discovered"   # manifest parsed, not yet enabled
    ENABLED = "enabled"         # on_load ran successfully
    DISABLED = "disabled"       # explicitly disabled (or never enabled this session)
    ERRORED = "errored"         # import or a lifecycle call raised


@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    state: PluginState = PluginState.DISCOVERED
    instance: WombatPlugin | None = None
    context: PluginContext | None = None
    error: str | None = None       # human-readable reason when state == ERRORED

    @property
    def id(self) -> str:
        return self.manifest.id


class PluginManager:
    """Owns the set of discovered plugins and their enable/disable lifecycle."""

    def __init__(self, plugins_root: Path, context_factory: ContextFactory) -> None:
        self._root = Path(plugins_root)
        self._make_context = context_factory
        self._plugins: dict[str, LoadedPlugin] = {}
        self._manifest_errors: list[tuple[Path, ManifestError]] = []

    # --------------------------------------------------------------- discovery

    def discover(self) -> list[LoadedPlugin]:
        """(Re)scan the plugins root. Preserves the state of already-enabled plugins."""
        manifests, self._manifest_errors = discover_with_errors(self._root)
        seen: set[str] = set()
        for m in manifests:
            seen.add(m.id)
            existing = self._plugins.get(m.id)
            if existing is None or existing.state in (PluginState.DISCOVERED, PluginState.ERRORED):
                # (Re)register; don't disturb a live enabled instance.
                if existing is None or existing.state != PluginState.ENABLED:
                    self._plugins[m.id] = LoadedPlugin(manifest=m)
        # Drop entries whose directory disappeared and that aren't live.
        for pid in list(self._plugins):
            if pid not in seen and self._plugins[pid].state != PluginState.ENABLED:
                del self._plugins[pid]
        return list(self._plugins.values())

    @property
    def plugins(self) -> list[LoadedPlugin]:
        return list(self._plugins.values())

    def get(self, plugin_id: str) -> LoadedPlugin | None:
        return self._plugins.get(plugin_id)

    @property
    def manifest_errors(self) -> list[tuple[Path, ManifestError]]:
        """Directories whose plugin.toml failed to parse during the last discover()."""
        return list(self._manifest_errors)

    @property
    def enabled_ids(self) -> list[str]:
        return [p.id for p in self._plugins.values() if p.state == PluginState.ENABLED]

    # ------------------------------------------------------------ enable/disable

    def enable(self, plugin_id: str) -> LoadedPlugin | None:
        """Import, instantiate, and on_load a plugin. Errors are isolated and logged."""
        lp = self._plugins.get(plugin_id)
        if lp is None:
            log.warning("enable(%r): no such plugin", plugin_id)
            return None
        if lp.state == PluginState.ENABLED:
            return lp

        if not lp.manifest.api_compatible:
            self._fail(
                lp,
                f"targets plugin API v{lp.manifest.api}, host is v{PLUGIN_API_VERSION}",
            )
            return lp

        instance = self._instantiate(lp)
        if instance is None:
            return lp  # _fail already recorded the error

        ctx = self._make_context(lp.manifest)
        lp.instance = instance
        lp.context = ctx
        try:
            instance.on_load(ctx)
        except Exception as exc:  # noqa: BLE001 — error boundary
            ctx._teardown()
            lp.instance = None
            lp.context = None
            self._fail(lp, f"on_load failed: {exc}", exc=exc)
            return lp

        lp.state = PluginState.ENABLED
        lp.error = None
        log.info("plugin enabled: %s (%s)", lp.manifest.name, lp.id)
        return lp

    def disable(self, plugin_id: str) -> LoadedPlugin | None:
        """Call on_unload and tear down the plugin's hooks. Errors are isolated."""
        lp = self._plugins.get(plugin_id)
        if lp is None or lp.state != PluginState.ENABLED:
            return lp
        if lp.instance is not None:
            try:
                lp.instance.on_unload()
            except Exception as exc:  # noqa: BLE001 — error boundary
                log.error("plugin %s on_unload raised: %s", lp.id, exc)
        if lp.context is not None:
            lp.context._teardown()
        lp.instance = None
        lp.context = None
        lp.state = PluginState.DISABLED
        log.info("plugin disabled: %s", lp.id)
        return lp

    def disable_all(self) -> None:
        """Disable every enabled plugin (e.g. on app shutdown)."""
        for pid in self.enabled_ids:
            self.disable(pid)

    # ------------------------------------------------------------------ import

    def _instantiate(self, lp: LoadedPlugin) -> WombatPlugin | None:
        m = lp.manifest
        directory = m.directory
        if directory is None:
            self._fail(lp, "manifest has no directory to import from")
            return None

        added_path = str(directory.parent)
        path_inserted = added_path not in sys.path
        if path_inserted:
            sys.path.insert(0, added_path)
        try:
            # Reload if already imported (stale from a previous enable in this session).
            if m.module_name in sys.modules:
                module = importlib.reload(sys.modules[m.module_name])
            else:
                module = importlib.import_module(m.module_name)
            cls = getattr(module, m.class_name, None)
            if cls is None:
                self._fail(lp, f"entry class {m.class_name!r} not found in {m.module_name!r}")
                return None
            if not (isinstance(cls, type) and issubclass(cls, WombatPlugin)):
                self._fail(lp, f"entry {m.entry!r} is not a WombatPlugin subclass")
                return None
            return cls()
        except Exception as exc:  # noqa: BLE001 — error boundary
            self._fail(lp, f"import failed: {exc}", exc=exc)
            return None
        finally:
            if path_inserted:
                try:
                    sys.path.remove(added_path)
                except ValueError:
                    pass

    def _fail(self, lp: LoadedPlugin, reason: str, *, exc: Exception | None = None) -> None:
        lp.state = PluginState.ERRORED
        lp.error = reason
        if exc is not None:
            log.error("plugin %s errored: %s", lp.id, reason, exc_info=exc)
        else:
            log.error("plugin %s errored: %s", lp.id, reason)
        return None
