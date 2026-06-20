"""Tests for WaveformLoader concurrency/lifecycle.

Same overlap that crashed beat detection ("QThread: Destroyed while thread is
still running"): a second load() arriving while the first extraction is still
blocked inside ffmpeg.
"""
from __future__ import annotations

import sys
import time

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import wombat.audio.waveform as waveform_mod  # noqa: E402
from wombat.audio.loader import WaveformLoader  # noqa: E402


def _wait_until(pred, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        _app.processEvents()
        if pred():
            return True
        time.sleep(0.005)
    _app.processEvents()
    return pred()


def _slow_extract(delay: float):
    def fake(path: str):
        time.sleep(delay)
        return path   # sentinel: the path doubles as the "waveform"
    return fake


def test_overlapping_loads_deliver_only_latest(monkeypatch):
    monkeypatch.setattr(waveform_mod, "extract_waveform", _slow_extract(0.1))
    loader = WaveformLoader()
    results: list = []
    loader.waveform_ready.connect(results.append)

    loader.load("A")
    loader.load("B")   # supersedes A while A is still running

    assert _wait_until(lambda: len(results) >= 1 and not loader._live)
    assert results == ["B"]          # A's result was abandoned
    loader.wait_all()


def test_cancel_is_nonblocking_and_abandons_result(monkeypatch):
    monkeypatch.setattr(waveform_mod, "extract_waveform", _slow_extract(0.15))
    loader = WaveformLoader()
    results: list = []
    loader.waveform_ready.connect(results.append)

    loader.load("A")
    t0 = time.time()
    loader.cancel()
    assert time.time() - t0 < 0.05   # did not block on the running extraction

    assert _wait_until(lambda: not loader._live)
    assert results == []


def test_threads_drain_after_completion(monkeypatch):
    monkeypatch.setattr(waveform_mod, "extract_waveform", _slow_extract(0.02))
    loader = WaveformLoader()
    results: list = []
    loader.waveform_ready.connect(results.append)

    loader.load("solo")
    assert _wait_until(lambda: results == ["solo"])
    assert _wait_until(lambda: not loader._live)   # cleaned itself up
