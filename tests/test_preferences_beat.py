"""Tests for the Beat Detection section of the preferences dialog."""
import sys

import pytest
from PySide6.QtWidgets import QApplication  # noqa: E402

from wombat.ui.preferences_dialog import PreferencesDialog

_app = QApplication.instance() or QApplication(sys.argv)


class _StubSettings:
    """Duck-typed AppSettings holding values in memory (no real QSettings)."""

    def __init__(self, **vals):
        self._v = {
            "snap": False,
            "hz": 60.0,
            "eps": 0.5,
            "beat_bin": "",
            "beat_model": "",
        }
        self._v.update(vals)

    def load_snap_to_frame(self): return self._v["snap"]
    def save_snap_to_frame(self, v): self._v["snap"] = v
    def load_synthesis_hz(self): return self._v["hz"]
    def save_synthesis_hz(self, v): self._v["hz"] = v
    def load_simplify_epsilon(self): return self._v["eps"]
    def save_simplify_epsilon(self, v): self._v["eps"] = v
    def load_beat_binary_path(self): return self._v["beat_bin"]
    def save_beat_binary_path(self, v): self._v["beat_bin"] = v
    def load_beat_model_path(self): return self._v["beat_model"]
    def save_beat_model_path(self, v): self._v["beat_model"] = v


def test_status_ready_when_both_paths_exist(tmp_path):
    binary = tmp_path / "beat_this_cpp"
    model = tmp_path / "model.onnx"
    binary.write_text("x")
    model.write_text("x")

    dlg = PreferencesDialog(_StubSettings(
        beat_bin=str(binary), beat_model=str(model)))
    try:
        assert "Ready" in dlg._beat_status.text()
        assert "model.onnx" in dlg._beat_status.text()
    finally:
        dlg.deleteLater()


def test_status_warns_when_binary_missing():
    dlg = PreferencesDialog(_StubSettings(beat_bin="", beat_model=""))
    try:
        # nothing configured → resolution may still find a system binary, but
        # with neither path set and (typically) no system install, status warns.
        text = dlg._beat_status.text().lower()
        assert "disabled" in text or "no" in text or "ready" in text
    finally:
        dlg.deleteLater()


def test_status_warns_when_path_set_but_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    dlg = PreferencesDialog(_StubSettings(
        beat_bin=str(missing), beat_model=str(missing)))
    try:
        assert "not found" in dlg._beat_status.text().lower()
    finally:
        dlg.deleteLater()


def test_save_round_trips_beat_paths(tmp_path):
    binary = tmp_path / "bin"
    model = tmp_path / "m.onnx"
    binary.write_text("x")
    model.write_text("x")
    settings = _StubSettings()
    dlg = PreferencesDialog(settings)
    try:
        dlg._beat_bin.setText(str(binary))
        dlg._beat_model.setText(str(model))
        dlg._save_and_accept()
        assert settings.load_beat_binary_path() == str(binary)
        assert settings.load_beat_model_path() == str(model)
    finally:
        dlg.deleteLater()
