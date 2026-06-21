"""Declarative settings UI for plugins.

A plugin returns a :class:`PanelSpec` from ``settings_panel()``; the host renders
it once into a real Qt widget via :func:`build_panel` and keeps it in a dock. This
replaces OFS's per-frame immediate-mode ``gui()`` — the plugin describes controls
and receives change callbacks, and the host owns layout/styling (so plugins inherit
theming and can't break the window).

The control set mirrors the OFS GUI surface we audited (Text, Button, Input,
IntInput, Slider, Checkbox, Combo, CollapsingHeader→Group, Separator, Tooltip),
plus a RawWidget escape hatch for fully custom panels.

This module is intentionally framework-thin: control specs are plain dataclasses
(no Qt), so a plugin's ``settings_panel()`` stays testable headless.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger("wombat.plugin")


# --------------------------------------------------------------- control specs

@dataclass(frozen=True)
class Control:
    """Base for all control specs. ``key`` is the value key reported on change."""

    tooltip: str = field(default="", kw_only=True)


@dataclass(frozen=True)
class Text(Control):
    text: str


@dataclass(frozen=True)
class Separator(Control):
    pass


@dataclass(frozen=True)
class Button(Control):
    key: str
    label: str
    on_click: Callable[[], None]


@dataclass(frozen=True)
class Checkbox(Control):
    key: str
    label: str
    value: bool = False


@dataclass(frozen=True)
class IntInput(Control):
    key: str
    label: str
    value: int = 0
    minimum: int = 0
    maximum: int = 100
    step: int = 1


@dataclass(frozen=True)
class FloatInput(Control):
    key: str
    label: str
    value: float = 0.0
    minimum: float = 0.0
    maximum: float = 1.0
    step: float = 0.1
    decimals: int = 2


@dataclass(frozen=True)
class IntSlider(Control):
    key: str
    label: str
    minimum: int = 0
    maximum: int = 100
    value: int = 0


@dataclass(frozen=True)
class TextInput(Control):
    key: str
    label: str
    value: str = ""


@dataclass(frozen=True)
class Combo(Control):
    key: str
    label: str
    options: Sequence[str] = ()
    value: int = 0   # selected index


@dataclass(frozen=True)
class Group(Control):
    title: str
    controls: Sequence[Control] = ()


@dataclass(frozen=True)
class RawWidget(Control):
    """Escape hatch: ``factory()`` builds and returns a custom QWidget."""

    factory: Callable[[], QWidget]


@dataclass(frozen=True)
class PanelSpec:
    """A plugin's settings panel: an ordered list of controls + a change callback."""

    controls: Sequence[Control] = ()
    on_change: Callable[[str, object], None] | None = None


# --------------------------------------------------------------- builder widget

class PluginSettingsWidget(QWidget):
    """Renders a PanelSpec. Exposes current values and a ``changed(key, value)`` signal."""

    changed = Signal(str, object)

    def __init__(self, spec: PanelSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.values: dict[str, object] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        self._build_into(root, spec.controls)
        root.addStretch(1)

    # -------------------------------------------------------------- internals

    def _emit(self, key: str, value: object) -> None:
        self.values[key] = value
        self.changed.emit(key, value)
        if self._spec.on_change is not None:
            try:
                self._spec.on_change(key, value)
            except Exception as exc:  # noqa: BLE001 — don't let a plugin crash the UI
                log.error("settings on_change(%r) failed: %s", key, exc, exc_info=exc)

    def _build_into(self, layout: QVBoxLayout, controls: Sequence[Control]) -> None:
        for control in controls:
            widget = self._build(control)
            if widget is not None:
                layout.addWidget(widget)

    def _row(self, label: str, widget: QWidget) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(label))
        h.addWidget(widget, 1)
        return row

    def _build(self, c: Control) -> QWidget | None:  # noqa: C901 — flat dispatch
        widget: QWidget | None = None

        if isinstance(c, Text):
            lbl = QLabel(c.text)
            lbl.setWordWrap(True)
            widget = lbl

        elif isinstance(c, Separator):
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            widget = line

        elif isinstance(c, Group):
            box = QGroupBox(c.title)
            inner = QVBoxLayout(box)
            self._build_into(inner, c.controls)
            widget = box

        elif isinstance(c, Button):
            btn = QPushButton(c.label)
            btn.clicked.connect(lambda _=False, cb=c.on_click, k=c.key: self._click(k, cb))
            widget = btn

        elif isinstance(c, Checkbox):
            cb = QCheckBox(c.label)
            cb.setChecked(c.value)
            self.values[c.key] = c.value
            cb.toggled.connect(lambda v, k=c.key: self._emit(k, bool(v)))
            widget = cb

        elif isinstance(c, IntInput):
            sb = QSpinBox()
            sb.setRange(c.minimum, c.maximum)
            sb.setSingleStep(c.step)
            sb.setValue(c.value)
            self.values[c.key] = c.value
            sb.valueChanged.connect(lambda v, k=c.key: self._emit(k, int(v)))
            widget = self._row(c.label, sb)

        elif isinstance(c, FloatInput):
            dsb = QDoubleSpinBox()
            dsb.setRange(c.minimum, c.maximum)
            dsb.setSingleStep(c.step)
            dsb.setDecimals(c.decimals)
            dsb.setValue(c.value)
            self.values[c.key] = c.value
            dsb.valueChanged.connect(lambda v, k=c.key: self._emit(k, float(v)))
            widget = self._row(c.label, dsb)

        elif isinstance(c, IntSlider):
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(c.minimum, c.maximum)
            sl.setValue(c.value)
            self.values[c.key] = c.value
            readout = QLabel(str(c.value))

            def _on_slide(v: int, k: str = c.key, r: QLabel = readout) -> None:
                r.setText(str(v))
                self._emit(k, int(v))

            sl.valueChanged.connect(_on_slide)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(QLabel(c.label))
            h.addWidget(sl, 1)
            h.addWidget(readout)
            widget = row

        elif isinstance(c, TextInput):
            le = QLineEdit(c.value)
            self.values[c.key] = c.value
            le.textChanged.connect(lambda v, k=c.key: self._emit(k, str(v)))
            widget = self._row(c.label, le)

        elif isinstance(c, Combo):
            combo = QComboBox()
            combo.addItems(list(c.options))
            combo.setCurrentIndex(c.value)
            self.values[c.key] = c.value
            combo.currentIndexChanged.connect(lambda v, k=c.key: self._emit(k, int(v)))
            widget = self._row(c.label, combo)

        elif isinstance(c, RawWidget):
            try:
                widget = c.factory()
            except Exception as exc:  # noqa: BLE001 — isolate a bad factory
                log.error("RawWidget factory failed: %s", exc, exc_info=exc)
                widget = None

        if widget is not None and c.tooltip:
            widget.setToolTip(c.tooltip)
        return widget

    def _click(self, key: str, handler: Callable[[], None]) -> None:
        try:
            handler()
        except Exception as exc:  # noqa: BLE001 — a button handler must not crash the UI
            log.error("button %r handler failed: %s", key, exc, exc_info=exc)


def build_panel(spec: PanelSpec, parent: QWidget | None = None) -> PluginSettingsWidget:
    """Render a PanelSpec into a Qt widget the host can dock."""
    return PluginSettingsWidget(spec, parent)
