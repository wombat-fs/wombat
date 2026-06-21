"""Tests for the TimecodeSpinBox value/text conversion."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from wombat.ui.time_spinbox import (  # noqa: E402
    TimecodeSpinBox,
    format_timecode,
    parse_timecode,
)


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0.0, "0:00.000"),
        (5.0, "0:05.000"),
        (83.5, "1:23.500"),
        (3723.0, "1:02:03.000"),
        (-12.25, "-0:12.250"),
    ],
)
def test_format_timecode(seconds, expected):
    assert format_timecode(seconds) == expected


def test_format_respects_decimals():
    assert format_timecode(83.0, decimals=0) == "1:23"
    assert format_timecode(83.5, decimals=1) == "1:23.5"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("83.5", 83.5),       # bare seconds
        ("1:23.5", 83.5),     # m:ss
        ("1:02:03", 3723.0),  # h:mm:ss
        ("0:05.000", 5.0),
        ("  12 ", 12.0),
        ("30s", 30.0),        # tolerate trailing s
        ("", 0.0),
        ("-0:12.25", -12.25),
    ],
)
def test_parse_timecode(text, expected):
    assert parse_timecode(text) == pytest.approx(expected)


def test_parse_invalid_returns_none():
    assert parse_timecode("abc") is None
    assert parse_timecode("1:2:3:4x") is None


def test_roundtrip_through_widget():
    sb = TimecodeSpinBox()
    sb.setRange(0.0, 10000.0)
    sb.setDecimals(3)
    sb.setValue(83.5)
    assert sb.text() == "1:23.500"
    assert sb.value() == pytest.approx(83.5)


def test_widget_accepts_typed_timecode():
    sb = TimecodeSpinBox()
    sb.setRange(0.0, 10000.0)
    # valueFromText is what the spinbox uses to interpret typed input
    assert sb.valueFromText("2:00") == pytest.approx(120.0)
    assert sb.valueFromText("45.25") == pytest.approx(45.25)
