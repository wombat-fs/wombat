"""PluginManifest — parsed `plugin.toml` metadata + discovery helpers.

A plugin is a directory containing a `plugin.toml` and an importable Python
package (or module) named by its `id`:

    plugins_root/
      motion_assist/
        plugin.toml
        __init__.py        # defines the WombatPlugin subclass

`plugin.toml`:

    [plugin]
    name = "Motion Assist"
    id = "motion_assist"
    version = "0.1.0"
    entry = "motion_assist:MotionAssistPlugin"   # module:Class
    api = "1"
    capabilities = ["edit_actions", "write_layer", "player_read"]
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Major version of the plugin API. A plugin declares the major it targets in
# `api = "N"`; a mismatch is refused at load time. Bump only on breaking changes
# to PluginContext / WombatPlugin.
PLUGIN_API_VERSION = 1

MANIFEST_FILENAME = "plugin.toml"

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ENTRY_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


class ManifestError(Exception):
    """Raised when a plugin.toml is missing required fields or is malformed."""


@dataclass(frozen=True)
class PluginManifest:
    """Validated metadata for one plugin."""

    id: str
    name: str
    version: str
    entry: str                       # "module:Class"
    api: int                         # major plugin-API version targeted
    capabilities: tuple[str, ...] = ()
    directory: Path | None = None    # install dir (None for in-memory/tests)
    description: str = ""

    @property
    def module_name(self) -> str:
        return self.entry.split(":", 1)[0]

    @property
    def class_name(self) -> str:
        return self.entry.split(":", 1)[1]

    @property
    def api_compatible(self) -> bool:
        """True if this plugin targets the host's current major API version."""
        return self.api == PLUGIN_API_VERSION

    # ------------------------------------------------------------------ parsing

    @classmethod
    def from_dict(cls, data: dict, *, directory: Path | None = None) -> PluginManifest:
        section = data.get("plugin")
        if not isinstance(section, dict):
            raise ManifestError("missing [plugin] table")

        def _req(key: str) -> object:
            if key not in section:
                raise ManifestError(f"missing required field plugin.{key}")
            return section[key]

        pid = _req("id")
        if not isinstance(pid, str) or not _ID_RE.match(pid):
            raise ManifestError(
                f"plugin.id {pid!r} must be a lowercase identifier (a-z, 0-9, _)"
            )

        entry = _req("entry")
        if not isinstance(entry, str) or not _ENTRY_RE.match(entry):
            raise ManifestError(f"plugin.entry {entry!r} must be of the form 'module:Class'")

        api_raw = section.get("api", PLUGIN_API_VERSION)
        try:
            api = int(api_raw)
        except (TypeError, ValueError):
            raise ManifestError(f"plugin.api {api_raw!r} must be an integer major version")

        caps = section.get("capabilities", [])
        if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
            raise ManifestError("plugin.capabilities must be a list of strings")

        return cls(
            id=pid,
            name=str(_req("name")),
            version=str(section.get("version", "0.0.0")),
            entry=entry,
            api=api,
            capabilities=tuple(caps),
            directory=directory,
            description=str(section.get("description", "")),
        )

    @classmethod
    def load(cls, manifest_path: Path) -> PluginManifest:
        """Parse a plugin.toml file. Raises ManifestError on any problem."""
        try:
            with open(manifest_path, "rb") as fh:
                data = tomllib.load(fh)
        except OSError as exc:
            raise ManifestError(f"cannot read {manifest_path}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ManifestError(f"invalid TOML in {manifest_path}: {exc}") from exc
        return cls.from_dict(data, directory=manifest_path.parent)


def discover(plugins_root: Path) -> list[PluginManifest]:
    """Scan ``plugins_root`` for plugin directories, returning valid manifests.

    Directories whose plugin.toml is missing or malformed are skipped (the caller
    can report them separately via :func:`discover_with_errors`).
    """
    return [m for m, _ in _scan(plugins_root) if m is not None]


def discover_with_errors(
    plugins_root: Path,
) -> tuple[list[PluginManifest], list[tuple[Path, ManifestError]]]:
    """Like :func:`discover` but also returns (dir, error) for malformed plugins."""
    ok: list[PluginManifest] = []
    bad: list[tuple[Path, ManifestError]] = []
    for manifest, err in _scan(plugins_root):
        if manifest is not None:
            ok.append(manifest)
        elif err is not None:
            bad.append(err)
    return ok, bad


def _scan(
    plugins_root: Path,
) -> list[tuple[PluginManifest | None, tuple[Path, ManifestError] | None]]:
    if not plugins_root.is_dir():
        return []
    results: list[tuple[PluginManifest | None, tuple[Path, ManifestError] | None]] = []
    for child in sorted(plugins_root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        try:
            results.append((PluginManifest.load(manifest_path), None))
        except ManifestError as exc:
            results.append((None, (child, exc)))
    return results
