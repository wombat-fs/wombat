"""Keybindings loader — comment-stripping and override merge."""
from __future__ import annotations

from pathlib import Path

import pytest

from wombat import keybindings


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Redirect config_path() to a temp file and return its Path."""
    path = tmp_path / "keybindings.json"
    monkeypatch.setattr(keybindings, "config_path", lambda: path)
    return path


def test_template_round_trips_through_load(cfg):
    """write_template() emits JSONC with // comments — load must still parse it."""
    keybindings.write_template()
    assert cfg.exists()
    assert "//" in cfg.read_text(encoding="utf-8")  # sanity: comments present

    bindings = keybindings.load()
    assert bindings["save"] == keybindings.DEFAULTS["save"]
    assert keybindings.load_action_keys() == keybindings._ACTION_KEY_DEFAULTS


def test_line_comments_stripped(cfg):
    cfg.write_text(
        '{\n'
        '  "save": "Ctrl+Alt+S",  // my override\n'
        '  "action_keys": ["\\\\", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]\n'
        '}\n',
        encoding="utf-8",
    )
    assert keybindings.load()["save"] == "Ctrl+Alt+S"
    assert keybindings.load_action_keys()[0] == "\\"


def test_double_slash_inside_string_preserved(cfg):
    """A // inside a string value must not be treated as a comment."""
    cfg.write_text('{"save": "a//b"}\n', encoding="utf-8")
    assert keybindings.load()["save"] == "a//b"


def test_missing_file_returns_defaults(cfg):
    assert not cfg.exists()
    assert keybindings.load() == keybindings.DEFAULTS
    assert keybindings.load_action_keys() == keybindings._ACTION_KEY_DEFAULTS


def test_malformed_json_falls_back(cfg):
    cfg.write_text("{ not valid json ", encoding="utf-8")
    assert keybindings.load() == keybindings.DEFAULTS
    assert keybindings.load_action_keys() == keybindings._ACTION_KEY_DEFAULTS
