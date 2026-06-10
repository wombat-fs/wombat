"""Tests for wombat.app.project — Project model, save/load, channel management."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# QApplication required for QObject / Signal.
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.app.project import Project  # noqa: E402
from wombat.domain.action import Action, ActionList  # noqa: E402

# ------------------------------------------------------------------ helpers

def _project_with_channel(
    name: str = "alpha", ats_pos: list[tuple[float, int]] | None = None
) -> Project:
    proj = Project.new()
    al = ActionList(Action(t, p) for t, p in (ats_pos or [(0.1, 0), (0.5, 100)]))
    proj.add_channel(name, actions=al)
    return proj


# ------------------------------------------------------------------ channel management

def test_add_channel():
    proj = Project.new()
    ch = proj.add_channel("alpha")
    assert len(proj.channels) == 1
    assert proj.channels[0].name == "alpha"
    assert ch is proj.channels[0]


def test_add_channel_with_actions():
    proj = Project.new()
    al = ActionList([Action(1.0, 50)])
    proj.add_channel("beta", actions=al)
    assert len(proj.channels[0].layers[0].actions) == 1


def test_remove_channel():
    proj = Project.new()
    proj.add_channel("alpha")
    proj.add_channel("beta")
    proj.remove_channel(0)
    assert len(proj.channels) == 1
    assert proj.channels[0].name == "beta"


def test_remove_channel_clamps_active_index():
    proj = Project.new()
    proj.add_channel("alpha")
    proj.add_channel("beta")
    proj.active_index = 1
    proj.remove_channel(1)
    assert proj.active_index == 0


def test_remove_out_of_bounds_is_noop():
    proj = Project.new()
    proj.add_channel("alpha")
    proj.remove_channel(5)  # should not raise
    assert len(proj.channels) == 1


def test_rename_channel():
    proj = Project.new()
    proj.add_channel("alpha")
    proj.rename_channel(0, "orig")
    assert proj.channels[0].name == "orig"


def test_move_channel_forward():
    proj = Project.new()
    proj.add_channel("a")
    proj.add_channel("b")
    proj.add_channel("c")
    proj.active_index = 0  # 'a'
    proj.move_channel(0, 2)
    assert [ch.name for ch in proj.channels] == ["b", "c", "a"]
    assert proj.active_index == 2  # followed 'a'


def test_move_channel_backward():
    proj = Project.new()
    proj.add_channel("a")
    proj.add_channel("b")
    proj.add_channel("c")
    proj.active_index = 2  # 'c'
    proj.move_channel(2, 0)
    assert [ch.name for ch in proj.channels] == ["c", "a", "b"]
    assert proj.active_index == 0  # followed 'c'


def test_set_active():
    proj = Project.new()
    proj.add_channel("alpha")
    proj.add_channel("beta")
    proj.set_active(1)
    assert proj.active_index == 1
    assert proj.active_channel.name == "beta"


def test_set_active_out_of_bounds_is_noop():
    proj = Project.new()
    proj.add_channel("alpha")
    proj.active_index = 0
    proj.set_active(99)
    assert proj.active_index == 0


# ------------------------------------------------------------------ channels_changed signal

def test_channels_changed_on_add():
    proj = Project.new()
    fired = []
    proj.channels_changed.connect(lambda: fired.append(1))
    proj.add_channel("alpha")
    assert len(fired) == 1


def test_channels_changed_on_remove():
    proj = Project.new()
    proj.add_channel("alpha")
    fired = []
    proj.channels_changed.connect(lambda: fired.append(1))
    proj.remove_channel(0)
    assert len(fired) == 1


def test_active_changed_signal():
    proj = Project.new()
    proj.add_channel("a")
    proj.add_channel("b")
    received = []
    proj.active_changed.connect(lambda i: received.append(i))
    proj.set_active(1)
    assert received == [1]


# ------------------------------------------------------------------ save / load roundtrip

def test_save_load_roundtrip():
    proj = _project_with_channel("alpha", [(0.1, 0), (0.5, 100)])
    proj.active_index = 0
    proj.view.offset = 1.5
    proj.view.visible_time = 10.0

    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "test.wombat")
        proj.save(path)

        loaded = Project.load(path)
        assert len(loaded.channels) == 1
        assert loaded.channels[0].name == "alpha"
        assert len(loaded.channels[0].layers[0].actions) == 2
        assert loaded.active_index == 0
        assert loaded.view.offset == pytest.approx(1.5)
        assert loaded.view.visible_time == pytest.approx(10.0)


def test_save_stores_at_as_float_seconds():
    """Verify .wombat stores at as float seconds, not int milliseconds."""
    proj = _project_with_channel("t", [(1.234567, 50)])

    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "test.wombat")
        proj.save(path)

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        at_val = data["channels"][0]["layers"][0]["actions"][0]["at"]
        assert isinstance(at_val, float)
        assert abs(at_val - 1.234567) < 1e-9


def test_load_restores_float_precision():
    proj = _project_with_channel("t", [(1.234567, 50)])

    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "test.wombat")
        proj.save(path)
        loaded = Project.load(path)
        assert loaded.channels[0].layers[0].actions[0].at == pytest.approx(1.234567)


def test_save_requires_path():
    proj = Project.new()
    with pytest.raises(ValueError):
        proj.save()


def test_load_bad_version_raises():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "bad.wombat")
        Path(path).write_text('{"wombat_project_version": 99, "channels": []}', encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported"):
            Project.load(path)


def test_multiple_channels_roundtrip():
    proj = Project.new()
    proj.add_channel("alpha", actions=ActionList([Action(0.1, 0)]))
    proj.add_channel("beta", actions=ActionList([Action(0.2, 50), Action(0.4, 100)]))
    proj.set_active(1)

    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "multi.wombat")
        proj.save(path)
        loaded = Project.load(path)

    assert len(loaded.channels) == 2
    assert loaded.channels[0].name == "alpha"
    assert loaded.channels[1].name == "beta"
    assert loaded.active_index == 1
    assert len(loaded.channels[1].layers[0].actions) == 2


# ------------------------------------------------------------------ path helpers

def test_make_relative_absolute_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "test.wombat")
        proj = Project.new()
        proj.path = path
        media = str(Path(d) / "clip.mp4")
        rel = proj.make_relative(media)
        assert rel == "clip.mp4"
        back = proj.make_absolute(rel)
        assert back == str(Path(media).resolve())


def test_make_relative_without_path_returns_abs():
    proj = Project.new()
    assert proj.make_relative("/some/path.mp4") == "/some/path.mp4"


def test_media_path_stored_relative_in_file():
    with tempfile.TemporaryDirectory() as d:
        media = Path(d) / "clip.mp4"
        media.touch()
        proj = Project.new(str(media))
        path = str(Path(d) / "test.wombat")
        proj.save(path)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["media"] == "clip.mp4"


# ------------------------------------------------------------------ export

def test_export_funscripts_creates_files():
    with tempfile.TemporaryDirectory() as d:
        media = Path(d) / "clip.mp4"
        media.touch()
        proj = Project.new(str(media))
        proj.add_channel("alpha", actions=ActionList([Action(0.1, 0), Action(0.5, 100)]))
        proj.add_channel("orig", actions=ActionList([Action(0.2, 50)]))

        written = proj.export_funscripts(out_dir=d)
        assert len(written) == 2
        names = {Path(p).name for p in written}
        assert "clip.alpha.funscript" in names
        assert "clip.funscript" in names


def test_export_skips_disabled_channels():
    with tempfile.TemporaryDirectory() as d:
        media = Path(d) / "clip.mp4"
        media.touch()
        proj = Project.new(str(media))
        proj.add_channel("alpha")
        proj.add_channel("beta")
        proj.channels[1].enabled = False

        written = proj.export_funscripts(out_dir=d)
        assert len(written) == 1
        assert Path(written[0]).name == "clip.alpha.funscript"


def test_export_overwrite_protection():
    with tempfile.TemporaryDirectory() as d:
        media = Path(d) / "clip.mp4"
        media.touch()
        proj = Project.new(str(media))
        proj.add_channel("alpha")
        (Path(d) / "clip.alpha.funscript").write_text("{}", encoding="utf-8")

        with pytest.raises(FileExistsError):
            proj.export_funscripts(out_dir=d)

        # overwrite=True should succeed
        written = proj.export_funscripts(out_dir=d, overwrite=True)
        assert len(written) == 1


def test_export_without_media_raises():
    proj = Project.new()
    proj.add_channel("alpha")
    with pytest.raises(ValueError, match="No media"):
        proj.export_funscripts()


def test_export_specific_channels():
    with tempfile.TemporaryDirectory() as d:
        media = Path(d) / "clip.mp4"
        media.touch()
        proj = Project.new(str(media))
        proj.add_channel("alpha")
        proj.add_channel("beta")

        written = proj.export_funscripts(out_dir=d, channels=[1])
        assert len(written) == 1
        assert Path(written[0]).name == "clip.beta.funscript"


# ------------------------------------------------------------------ dirty flag

def test_dirty_flag():
    proj = Project.new()
    assert not proj.has_unsaved_edits()
    proj.mark_dirty()
    assert proj.has_unsaved_edits()
    proj.mark_clean()
    assert not proj.has_unsaved_edits()


def test_save_clears_dirty():
    proj = _project_with_channel()
    proj.mark_dirty()
    with tempfile.TemporaryDirectory() as d:
        proj.save(str(Path(d) / "test.wombat"))
    assert not proj.has_unsaved_edits()


# ------------------------------------------------------------------ discover siblings

def test_discover_and_load_siblings():
    from wombat.domain.funscript import Funscript, FunscriptMetadata
    from wombat.domain.funscript_io import save_funscript

    with tempfile.TemporaryDirectory() as d:
        media = Path(d) / "clip.mp4"
        media.touch()

        # Write two sibling funscripts
        for suffix in ["", ".alpha"]:
            al = ActionList([Action(0.1, 0), Action(0.5, 100)])
            fs = Funscript(
                actions=al,
                metadata=FunscriptMetadata(),
            )
            fname = f"clip{suffix}.funscript"
            save_funscript(str(Path(d) / fname), fs)

        proj = Project.new()
        proj.discover_and_load_siblings(str(media))

        assert len(proj.channels) == 2
        names = {ch.name for ch in proj.channels}
        assert "orig" in names  # "" → "orig"
        assert "alpha" in names
