"""Project — multi-channel document model.

Replaces the Phase 3/4 Session. Stores channels, active index, view state,
and the path to the .wombat project file. Handles save/load, channel
management, multi-axis import/export, and path helpers.

.wombat format stores `at` as float seconds (full precision).
Exported .funscript files quantize to ms via the normal funscript_io path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from wombat.domain.action import Action, ActionList
from wombat.domain.channel import BlendMode, Channel, FadeCurve, Layer
from wombat.domain.chapter import Chapter
from wombat.domain.funscript_io import FunscriptError, load_funscript, save_funscript

PROJECT_VERSION = 1
PROJECT_EXT = ".wombat"


@dataclass
class ViewState:
    offset: float = 0.0
    visible_time: float = 5.0


class Project(QObject):
    channels_changed = Signal()
    active_changed = Signal(int)
    chapters_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.media_path: str | None = None
        self.channels: list[Channel] = []
        self.active_index: int = 0
        self.path: str | None = None
        self.view: ViewState = ViewState()
        self.chapters: list[Chapter] = []
        self._dirty: bool = False

    # ----------------------------------------------------------------- lifecycle

    @classmethod
    def new(cls, media_path: str | None = None) -> Project:
        proj = cls()
        proj.media_path = media_path
        return proj

    @classmethod
    def load(cls, path: str) -> Project:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError as exc:
            raise OSError(f"Cannot read project: {exc}") from exc
        proj = cls()
        proj.path = path
        proj._from_dict(data, Path(path).parent)
        return proj

    def save(self, path: str | None = None) -> None:
        if path is not None:
            self.path = path
        if self.path is None:
            raise ValueError("No path for project")
        data = self._to_dict(Path(self.path).parent)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self._dirty = False

    def has_unsaved_edits(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        self._dirty = True

    def mark_clean(self) -> None:
        self._dirty = False

    # ----------------------------------------------------------------- channels

    def add_channel(self, name: str, *, actions: ActionList | None = None) -> Channel:
        al = actions.copy() if actions is not None else ActionList()
        ch = Channel(name=name, layers=[Layer(actions=al)])
        self.channels.append(ch)
        self.channels_changed.emit()
        return ch

    def import_funscript(self, path: str, name: str | None = None) -> Channel:
        fs = load_funscript(path)
        ch_name = name if name is not None else Path(path).stem
        ch = Channel.from_funscript(fs, name=ch_name)
        self.channels.append(ch)
        self.channels_changed.emit()
        return ch

    def remove_channel(self, index: int) -> None:
        if not (0 <= index < len(self.channels)):
            return
        del self.channels[index]
        if self.active_index >= len(self.channels):
            self.active_index = max(0, len(self.channels) - 1)
        self.channels_changed.emit()

    def rename_channel(self, index: int, name: str) -> None:
        if not (0 <= index < len(self.channels)):
            return
        self.channels[index].name = name
        self.channels_changed.emit()

    def move_channel(self, src: int, dst: int) -> None:
        n = len(self.channels)
        if not (0 <= src < n and 0 <= dst < n and src != dst):
            return
        ch = self.channels.pop(src)
        self.channels.insert(dst, ch)
        if self.active_index == src:
            self.active_index = dst
        elif src < self.active_index <= dst:
            self.active_index -= 1
        elif dst <= self.active_index < src:
            self.active_index += 1
        self.channels_changed.emit()

    def set_active(self, index: int) -> None:
        if not (0 <= index < len(self.channels)):
            return
        self.active_index = index
        self.active_changed.emit(index)

    @property
    def active_channel(self) -> Channel:
        return self.channels[self.active_index]

    # ----------------------------------------------------------------- chapters

    def add_chapter(
        self,
        at: float,
        name: str = "",
        end: float | None = None,
    ) -> Chapter:
        ch = Chapter(at=at, name=name, end=end)
        self.chapters.append(ch)
        self.chapters.sort()
        self.chapters_changed.emit()
        self.mark_dirty()
        return ch

    def remove_chapter(self, chapter: Chapter) -> None:
        try:
            self.chapters.remove(chapter)
        except ValueError:
            return
        self.chapters_changed.emit()
        self.mark_dirty()

    def rename_chapter(self, chapter: Chapter, name: str) -> None:
        if chapter in self.chapters:
            chapter.name = name
            self.chapters_changed.emit()
            self.mark_dirty()

    def move_chapter(self, chapter: Chapter, new_at: float) -> None:
        if chapter in self.chapters:
            chapter.at = new_at
            self.chapters.sort()
            self.chapters_changed.emit()
            self.mark_dirty()

    def chapter_before(self, t: float) -> Chapter | None:
        """Last chapter strictly before t, or None."""
        before = [c for c in self.chapters if c.at < t - 1e-6]
        return before[-1] if before else None

    def chapter_after(self, t: float) -> Chapter | None:
        """First chapter strictly after t, or None."""
        after = [c for c in self.chapters if c.at > t + 1e-6]
        return after[0] if after else None

    # ----------------------------------------------------------------- multi-axis

    def discover_and_load_siblings(self, media_path: str) -> None:
        """Auto-load base.funscript and base.*.funscript siblings next to media."""
        from wombat.app.naming import discover_siblings
        self.media_path = media_path
        for channel_name, fs_path in discover_siblings(media_path):
            try:
                fs = load_funscript(fs_path)
            except (FunscriptError, OSError):
                continue
            display_name = channel_name if channel_name else "orig"
            ch = Channel.from_funscript(fs, name=display_name)
            self.channels.append(ch)
        if self.channels:
            self.channels_changed.emit()

    def export_funscripts(
        self,
        out_dir: str | None = None,
        channels: list[int] | None = None,
        overwrite: bool = False,
    ) -> list[str]:
        """Write enabled channels to <base>.<channel>.funscript files.

        Raises FileExistsError on conflict unless overwrite=True.
        Raises ValueError if media_path is not set.
        """
        from wombat.app.naming import channel_filename
        if self.media_path is None:
            raise ValueError("No media path — cannot determine export filenames")

        base = Path(self.media_path).stem
        target_dir = Path(out_dir) if out_dir else Path(self.media_path).parent
        indices = channels if channels is not None else list(range(len(self.channels)))

        written: list[str] = []
        for i in indices:
            ch = self.channels[i]
            if not ch.enabled:
                continue
            fname = channel_filename(base, ch.name)
            dest = target_dir / fname
            if dest.exists() and not overwrite:
                raise FileExistsError(str(dest))
            fs = ch.to_funscript()
            save_funscript(str(dest), fs)
            written.append(str(dest))
        return written

    # ----------------------------------------------------------------- paths

    def make_relative(self, abs_path: str) -> str:
        if self.path is None:
            return abs_path
        try:
            return str(Path(abs_path).relative_to(Path(self.path).parent))
        except ValueError:
            return abs_path

    def make_absolute(self, rel_path: str) -> str:
        if self.path is None:
            return rel_path
        return str((Path(self.path).parent / rel_path).resolve())

    # ----------------------------------------------------------------- serialise

    def _to_dict(self, base_dir: Path) -> dict:
        media_rel: str | None = None
        if self.media_path is not None:
            try:
                media_rel = str(Path(self.media_path).relative_to(base_dir))
            except ValueError:
                media_rel = self.media_path
        return {
            "wombat_project_version": PROJECT_VERSION,
            "media": media_rel,
            "active_channel": self.active_index,
            "view": {"offset": self.view.offset, "visible_time": self.view.visible_time},
            "channels": [_channel_to_dict(ch) for ch in self.channels],
            "chapters": [_chapter_to_dict(c) for c in self.chapters],
        }

    def _from_dict(self, data: dict, base_dir: Path) -> None:
        ver = data.get("wombat_project_version", 0)
        if ver != PROJECT_VERSION:
            raise ValueError(f"Unsupported project version: {ver}")
        media = data.get("media")
        if media is not None:
            candidate = (base_dir / media).resolve()
            self.media_path = str(candidate)
        v = data.get("view", {})
        self.view = ViewState(
            offset=float(v.get("offset", 0.0)),
            visible_time=float(v.get("visible_time", 5.0)),
        )
        self.channels = [_channel_from_dict(c) for c in data.get("channels", [])]
        idx = int(data.get("active_channel", 0))
        self.active_index = max(0, min(idx, max(0, len(self.channels) - 1)))
        self.chapters = sorted(
            _chapter_from_dict(c) for c in data.get("chapters", [])
        )


# ------------------------------------------------------------------ helpers

def _layer_to_dict(layer: Layer) -> dict:
    d: dict = {
        "name": layer.name,
        "enabled": layer.enabled,
        "blend": layer.blend.value,
        "span": list(layer.span) if layer.span else None,
        "fade_in": layer.fade_in,
        "fade_out": layer.fade_out,
        "center": layer.center,
        "fade_curve": layer.fade_curve.value,
        "actions": [{"at": a.at, "pos": a.pos} for a in layer.actions],
    }
    if layer.event_name is not None:
        d["event_name"] = layer.event_name
        d["event_group_id"] = layer.event_group_id
        d["event_start_ms"] = layer.event_start_ms
        d["event_param_overrides"] = layer.event_param_overrides
    return d


def _layer_from_dict(d: dict) -> Layer:
    actions = ActionList(
        Action(float(a["at"]), int(a["pos"])) for a in d.get("actions", [])
    )
    span_raw = d.get("span")
    span: tuple[float, float] | None = (
        (float(span_raw[0]), float(span_raw[1])) if span_raw else None
    )
    layer = Layer(
        actions=actions,
        name=str(d.get("name", "base")),
        enabled=bool(d.get("enabled", True)),
        blend=BlendMode(d.get("blend", "override")),
        span=span,
        fade_in=float(d.get("fade_in", 0.0)),
        fade_out=float(d.get("fade_out", 0.0)),
        center=int(d.get("center", 50)),
        fade_curve=FadeCurve(d.get("fade_curve", "smooth")),
    )
    if "event_name" in d:
        layer.event_name = d["event_name"]
        layer.event_group_id = d.get("event_group_id")
        layer.event_start_ms = d.get("event_start_ms")
        layer.event_param_overrides = dict(d.get("event_param_overrides") or {})
    return layer


def _channel_to_dict(ch: Channel) -> dict:
    return {
        "name": ch.name,
        "enabled": ch.enabled,
        "layers": [_layer_to_dict(lay) for lay in ch.layers],
        "metadata": _metadata_to_dict(ch.metadata),
    }


def _channel_from_dict(d: dict) -> Channel:
    return Channel(
        name=str(d.get("name", "channel")),
        enabled=bool(d.get("enabled", True)),
        layers=[_layer_from_dict(lay) for lay in d.get("layers", [])],
        metadata=_metadata_from_dict(d.get("metadata", {})),
    )


def _metadata_to_dict(m) -> dict:
    return {
        "title": m.title,
        "creator": m.creator,
        "description": m.description,
        "tags": list(m.tags),
        "performers": list(m.performers),
        "script_url": m.script_url,
        "video_url": m.video_url,
        "license": m.license,
        "notes": m.notes,
    }


def _metadata_from_dict(d: dict):
    from wombat.domain.funscript import FunscriptMetadata
    return FunscriptMetadata(
        title=str(d.get("title", "")),
        creator=str(d.get("creator", "")),
        description=str(d.get("description", "")),
        tags=list(d.get("tags", [])),
        performers=list(d.get("performers", [])),
        script_url=str(d.get("script_url", "")),
        video_url=str(d.get("video_url", "")),
        license=str(d.get("license", "")),
        notes=str(d.get("notes", "")),
    )


def _chapter_to_dict(c: Chapter) -> dict:
    d: dict = {"at": c.at, "name": c.name}
    if c.end is not None:
        d["end"] = c.end
    return d


def _chapter_from_dict(d: dict) -> Chapter:
    end_raw = d.get("end")
    return Chapter(
        at=float(d["at"]),
        name=str(d.get("name", "")),
        end=float(end_raw) if end_raw is not None else None,
    )
