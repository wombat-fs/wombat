"""SnippetPanel — pick a pattern generator, tune parameters, preview, insert as layer.

Param controls are auto-generated from each generator's param_specs() so there
is no per-snippet UI code.  All heavy lifting happens in domain/snippets/.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wombat.domain.action import ActionList
from wombat.domain.channel import BlendMode
from wombat.domain.snippets.base import BeatSnippet, ParamSpec, WaveformSnippet
from wombat.domain.snippets.library import PRESETS, SnippetEntry
from wombat.domain.snippets.positions import (
    AlternateOverBase,
    Alternate,
    Constant,
    FollowBase,
    Ramp,
    Random,
    Sawtooth,
    Sine,
    Square,
    Triangle,
)
from wombat.domain.snippets.rhythms import (
    Accelerando,
    ConstantBeat,
    Euclidean,
    Subdivided,
    Swing,
)

log = logging.getLogger(__name__)

_RHYTHMS: dict[str, type] = {
    "Constant Beat": ConstantBeat,
    "Subdivided": Subdivided,
    "Swing": Swing,
    "Euclidean": Euclidean,
    "Accelerando": Accelerando,
}

_POS_ALGOS: dict[str, type] = {
    "Alternate": Alternate,
    "Constant": Constant,
    "Ramp": Ramp,
    "Random": Random,
    "Sine": Sine,
    "Triangle": Triangle,
    "Square": Square,
    "Sawtooth": Sawtooth,
    "Alternate Over Base": AlternateOverBase,
    "Follow Base": FollowBase,
}


# ------------------------------------------------------------------ preview canvas

class _PreviewCanvas(QWidget):
    """Mini canvas showing generated actions as dots + polyline."""

    _MIN_H = 120

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(self._MIN_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._actions: ActionList = ActionList()
        self._span: tuple[float, float] = (0.0, 5.0)

    def set_preview(self, actions: ActionList, span: tuple[float, float]) -> None:
        self._actions = actions
        self._span = span
        self.update()

    def paintEvent(self, _event: Any) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(30, 30, 30))

        # horizontal centre line at pos=50
        p.setPen(QPen(QColor(60, 60, 60), 1))
        mid_y = int(h * 0.5)
        p.drawLine(0, mid_y, w, mid_y)

        if not self._actions:
            p.end()
            return

        start, end = self._span
        duration = max(end - start, 1e-6)

        def to_px(t: float, pos: int) -> tuple[int, int]:
            x = int((t - start) / duration * (w - 2)) + 1
            y = int((1.0 - pos / 100.0) * (h - 4)) + 2
            return x, y

        # Draw connecting lines
        pts = [to_px(a.at, a.pos) for a in self._actions]
        if len(pts) >= 2:
            p.setPen(QPen(QColor(80, 160, 220), 1))
            for i in range(len(pts) - 1):
                p.drawLine(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])

        # Draw action dots
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(120, 200, 255))
        for x, y in pts:
            p.drawEllipse(x - 2, y - 2, 5, 5)

        p.end()


# ------------------------------------------------------------------ param control builder

def _make_control(spec: ParamSpec) -> QWidget:
    """Build a single control widget for a ParamSpec."""
    if spec.kind == "bool":
        cb = QCheckBox()
        cb.setChecked(bool(spec.default))
        cb.setProperty("_spec_key", spec.key)
        return cb
    if spec.kind == "choice":
        cb2 = QComboBox()
        for ch in (spec.choices or []):
            cb2.addItem(ch)
        idx = (spec.choices or []).index(spec.default) if spec.default in (spec.choices or []) else 0
        cb2.setCurrentIndex(idx)
        cb2.setProperty("_spec_key", spec.key)
        return cb2
    if spec.kind == "int":
        sb = QSpinBox()
        sb.setMinimum(int(spec.min) if spec.min is not None else -9999)
        sb.setMaximum(int(spec.max) if spec.max is not None else 9999)
        sb.setSingleStep(int(spec.step) if spec.step is not None else 1)
        sb.setValue(int(spec.default))
        sb.setProperty("_spec_key", spec.key)
        return sb
    # float
    dsb = QDoubleSpinBox()
    dsb.setMinimum(float(spec.min) if spec.min is not None else -9999.0)
    dsb.setMaximum(float(spec.max) if spec.max is not None else 9999.0)
    dsb.setSingleStep(float(spec.step) if spec.step is not None else 0.1)
    dsb.setDecimals(3)
    dsb.setValue(float(spec.default))
    dsb.setProperty("_spec_key", spec.key)
    return dsb


def _read_control(w: QWidget) -> Any:
    """Read the current value from a param control widget."""
    if isinstance(w, QCheckBox):
        return w.isChecked()
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QSpinBox):
        return w.value()
    if isinstance(w, QDoubleSpinBox):
        return w.value()
    return None


def _connect_control(w: QWidget, slot: Any) -> None:
    if isinstance(w, QCheckBox):
        w.stateChanged.connect(slot)
    elif isinstance(w, QComboBox):
        w.currentIndexChanged.connect(slot)
    elif isinstance(w, QSpinBox):
        w.valueChanged.connect(slot)
    elif isinstance(w, QDoubleSpinBox):
        w.valueChanged.connect(slot)


# ------------------------------------------------------------------ main panel

class SnippetPanel(QWidget):
    """Snippet builder panel — choose generator, tune params, preview, insert."""

    def __init__(
        self,
        editor: Any,     # EditorController (avoid circular import)
        player: Any,     # VideoPlayer
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._player = player
        self._param_controls: dict[str, QWidget] = {}
        self._rhythm_controls: dict[str, QWidget] = {}
        self._pos_controls: dict[str, QWidget] = {}
        self._current_entry: SnippetEntry | None = None
        self._editing_layer_index: int | None = None  # set when editing an existing snippet layer
        self._syncing: bool = False                   # guard against re-entry during load
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)  # ms debounce
        self._preview_timer.timeout.connect(self._refresh_preview)

        self._build_ui()
        self._populate_presets()
        self._on_preset_changed(0)

        editor.layer_structure_changed.connect(self._sync_active_layer)
        editor.selection_changed.connect(self._sync_active_layer)

    # ------------------------------------------------------------------ UI construction

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

        # Preset picker
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self._preset_combo = QComboBox()
        self._preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        preset_row.addWidget(self._preset_combo)
        root.addLayout(preset_row)

        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(self._desc_label)

        # Param controls (scrollable)
        self._param_scroll = QScrollArea()
        self._param_scroll.setWidgetResizable(True)
        self._param_scroll.setMaximumHeight(200)
        self._param_container = QWidget()
        self._param_form = QFormLayout(self._param_container)
        self._param_form.setSpacing(4)
        self._param_scroll.setWidget(self._param_container)
        root.addWidget(self._param_scroll)

        # Preview canvas
        preview_box = QGroupBox("Preview")
        pb_layout = QVBoxLayout(preview_box)
        pb_layout.setContentsMargins(4, 4, 4, 4)
        self._canvas = _PreviewCanvas()
        pb_layout.addWidget(self._canvas)
        root.addWidget(preview_box)

        # Span controls
        span_box = QGroupBox("Span")
        span_layout = QFormLayout(span_box)
        span_layout.setSpacing(4)

        self._span_start = QDoubleSpinBox()
        self._span_start.setRange(0.0, 99999.0)
        self._span_start.setDecimals(3)
        self._span_start.setSingleStep(0.1)
        self._span_start.setValue(0.0)
        self._span_start.setSuffix(" s")
        self._span_start.valueChanged.connect(self._schedule_preview)
        span_layout.addRow("Start:", self._span_start)

        self._span_dur = QDoubleSpinBox()
        self._span_dur.setRange(0.01, 99999.0)
        self._span_dur.setDecimals(3)
        self._span_dur.setSingleStep(0.5)
        self._span_dur.setValue(5.0)
        self._span_dur.setSuffix(" s")
        self._span_dur.valueChanged.connect(self._schedule_preview)
        span_layout.addRow("Duration:", self._span_dur)

        use_sel_btn = QPushButton("Use selection")
        use_sel_btn.clicked.connect(self._use_selection_span)
        span_layout.addRow("", use_sel_btn)

        root.addWidget(span_box)

        # Blend / fade
        blend_box = QGroupBox("Layer options")
        blend_layout = QFormLayout(blend_box)
        blend_layout.setSpacing(4)

        self._blend_combo = QComboBox()
        self._blend_combo.addItem("Additive", BlendMode.ADDITIVE)
        self._blend_combo.addItem("Override", BlendMode.OVERRIDE)
        self._blend_combo.addItem("Multiply", BlendMode.MULTIPLY)
        blend_layout.addRow("Blend:", self._blend_combo)

        self._fade_in_sb = QDoubleSpinBox()
        self._fade_in_sb.setRange(0.0, 60.0)
        self._fade_in_sb.setDecimals(2)
        self._fade_in_sb.setSingleStep(0.1)
        self._fade_in_sb.setSuffix(" s")
        blend_layout.addRow("Fade in:", self._fade_in_sb)

        self._fade_out_sb = QDoubleSpinBox()
        self._fade_out_sb.setRange(0.0, 60.0)
        self._fade_out_sb.setDecimals(2)
        self._fade_out_sb.setSingleStep(0.1)
        self._fade_out_sb.setSuffix(" s")
        blend_layout.addRow("Fade out:", self._fade_out_sb)

        root.addWidget(blend_box)

        # Insert / Update button (label changes based on edit mode)
        self._insert_btn = QPushButton("Insert as Layer")
        self._insert_btn.setFixedHeight(32)
        self._insert_btn.clicked.connect(self._insert)
        root.addWidget(self._insert_btn)

        root.addStretch()

        # Wire preset combo after everything is built
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)

    # ------------------------------------------------------------------ preset list

    def _populate_presets(self) -> None:
        prev = self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        for entry in PRESETS:
            self._preset_combo.addItem(f"[{entry.category}] {entry.name}", entry)
        self._preset_combo.blockSignals(prev)

    # ------------------------------------------------------------------ param controls

    def _clear_params(self) -> None:
        while self._param_form.rowCount() > 0:
            self._param_form.removeRow(0)
        self._param_controls.clear()

    def _build_params(self, specs: list[ParamSpec]) -> None:
        self._clear_params()
        for spec in specs:
            w = _make_control(spec)
            _connect_control(w, self._schedule_preview)
            self._param_controls[spec.key] = w
            self._param_form.addRow(spec.label + ":", w)

    def _collect_params(self) -> dict[str, Any]:
        return {key: _read_control(w) for key, w in self._param_controls.items()}

    # ------------------------------------------------------------------ snippet construction

    def _build_snippet(self) -> BeatSnippet | WaveformSnippet | None:
        entry = self._current_entry
        if entry is None:
            return None
        params = self._collect_params()
        try:
            if isinstance(entry.snippet, WaveformSnippet):
                return WaveformSnippet(**params, name=entry.name)  # type: ignore[arg-type]
            if isinstance(entry.snippet, BeatSnippet):
                # rebuild with same rhythm/pos classes but new params
                rhythm_cls = type(entry.snippet.rhythm)
                pos_cls = type(entry.snippet.pos)
                rhythm_specs = {s.key: s for s in rhythm_cls.param_specs()}
                pos_specs = {s.key: s for s in pos_cls.param_specs()}
                rhythm_params = {k: v for k, v in params.items() if k in rhythm_specs}
                pos_params = {k: v for k, v in params.items() if k in pos_specs}
                rhythm = rhythm_cls(**rhythm_params)
                pos = pos_cls(**pos_params)
                return BeatSnippet(rhythm=rhythm, pos=pos, name=entry.name)
        except Exception as exc:
            log.debug("Snippet build error: %s", exc)
        return None

    # ------------------------------------------------------------------ slots

    @Slot(int)
    def _on_preset_changed(self, index: int) -> None:
        entry: SnippetEntry | None = self._preset_combo.currentData()
        self._current_entry = entry
        if entry is None:
            self._clear_params()
            return
        if not self._syncing and self._editing_layer_index is not None:
            self._exit_update_mode()
        self._desc_label.setText(entry.description)
        # Collect all param specs for this snippet
        snippet = entry.snippet
        if isinstance(snippet, WaveformSnippet):
            specs = WaveformSnippet.param_specs()
            # seed controls with current snippet values
            for spec in specs:
                spec = ParamSpec(
                    key=spec.key, label=spec.label, kind=spec.kind,
                    default=getattr(snippet, spec.key, spec.default),
                    min=spec.min, max=spec.max, step=spec.step, choices=spec.choices,
                )
            self._build_params(WaveformSnippet.param_specs())
            # override defaults with actual preset values
            for spec in WaveformSnippet.param_specs():
                w = self._param_controls.get(spec.key)
                val = getattr(snippet, spec.key, None)
                if w is not None and val is not None:
                    self._set_control_value(w, val)
        elif isinstance(snippet, BeatSnippet):
            rhythm_specs = type(snippet.rhythm).param_specs()
            pos_specs = type(snippet.pos).param_specs()
            # Merge, rhythm first — keys must be disjoint or last wins
            all_specs = rhythm_specs + pos_specs
            self._build_params(all_specs)
            # seed with actual preset values
            for spec in rhythm_specs:
                w = self._param_controls.get(spec.key)
                val = getattr(snippet.rhythm, spec.key, None)
                if w is not None and val is not None:
                    self._set_control_value(w, val)
            for spec in pos_specs:
                w = self._param_controls.get(spec.key)
                val = getattr(snippet.pos, spec.key, None)
                if w is not None and val is not None:
                    self._set_control_value(w, val)
        self._schedule_preview()

    def _set_control_value(self, w: QWidget, val: Any) -> None:
        blocked = w.blockSignals(True)
        try:
            if isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, QComboBox):
                idx = w.findText(str(val))
                if idx >= 0:
                    w.setCurrentIndex(idx)
            elif isinstance(w, QSpinBox):
                w.setValue(int(val))
            elif isinstance(w, QDoubleSpinBox):
                w.setValue(float(val))
        finally:
            w.blockSignals(blocked)

    @Slot()
    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    @Slot()
    def _refresh_preview(self) -> None:
        snippet = self._build_snippet()
        if snippet is None:
            return
        span = self._current_span()
        try:
            actions = snippet.generate(span)
        except Exception as exc:
            log.debug("Preview generate error: %s", exc)
            return
        self._canvas.set_preview(actions, span)

    @Slot()
    def _use_selection_span(self) -> None:
        if not self._editor.has_active_channel:
            return
        sel = self._editor.selection
        if len(sel) < 2:
            # fall back to playhead ± 5 s
            t = self._player.position
            self._span_start.setValue(max(0.0, t))
            self._span_dur.setValue(5.0)
            return
        t0 = min(sel)
        t1 = max(sel)
        self._span_start.setValue(t0)
        self._span_dur.setValue(max(0.01, t1 - t0))

    @Slot()
    def _insert(self) -> None:
        snippet = self._build_snippet()
        if snippet is None:
            return
        if not self._editor.has_active_channel:
            return
        span = self._current_span()
        blend_data = self._blend_combo.currentData()
        blend = blend_data if isinstance(blend_data, BlendMode) else BlendMode.ADDITIVE
        entry = self._current_entry
        name = entry.name if entry else "snippet"
        if self._editing_layer_index is not None:
            self._editor.update_snippet_layer(
                self._editing_layer_index,
                snippet,
                span,
                blend=blend,
                fade_in=self._fade_in_sb.value(),
                fade_out=self._fade_out_sb.value(),
            )
        else:
            self._editor.insert_snippet_as_layer(
                snippet,
                span,
                blend=blend,
                name=name,
                fade_in=self._fade_in_sb.value(),
                fade_out=self._fade_out_sb.value(),
            )

    # ------------------------------------------------------------------ snippet layer editing

    @Slot()
    def _sync_active_layer(self) -> None:
        """Called when the active layer changes — enter or exit update mode as needed."""
        if self._syncing:
            return
        if not self._editor.has_active_channel:
            self._exit_update_mode()
            return
        ch = self._editor.active_channel
        li = self._editor.active_layer_index
        if not (0 <= li < len(ch.layers)):
            self._exit_update_mode()
            return
        layer = ch.layers[li]
        if layer.snippet is None:
            self._exit_update_mode()
            return
        if self._editing_layer_index == li:
            return  # already editing this layer — don't overwrite user's in-progress edits
        self._load_from_layer(layer, li)

    def _load_from_layer(self, layer, li: int) -> None:
        """Populate the panel from a snippet layer and enter update mode."""
        entry_name = layer.snippet_entry_name
        target_idx = -1
        for i in range(self._preset_combo.count()):
            e = self._preset_combo.itemData(i)
            if e is not None and e.name == entry_name:
                target_idx = i
                break
        if target_idx == -1:
            return  # unknown preset — can't reconstruct UI

        self._syncing = True
        try:
            self._preset_combo.blockSignals(True)
            self._preset_combo.setCurrentIndex(target_idx)
            self._preset_combo.blockSignals(False)
            self._current_entry = self._preset_combo.currentData()
            # Rebuild controls with entry defaults, then override with stored values
            self._on_preset_changed(target_idx)
            self._seed_controls_from_snippet(layer.snippet)
            # Set span and layer options from the layer
            if layer.span is not None:
                start, end = layer.span
                self._span_start.setValue(start)
                self._span_dur.setValue(max(0.01, end - start))
            idx = self._blend_combo.findData(layer.blend)
            if idx >= 0:
                self._blend_combo.setCurrentIndex(idx)
            self._fade_in_sb.setValue(layer.fade_in)
            self._fade_out_sb.setValue(layer.fade_out)
        finally:
            self._syncing = False

        self._editing_layer_index = li
        self._insert_btn.setText("Update Layer")

    def _exit_update_mode(self) -> None:
        if self._editing_layer_index is not None:
            self._editing_layer_index = None
            self._insert_btn.setText("Insert as Layer")

    def _seed_controls_from_snippet(self, snippet) -> None:
        """Override param controls with values from a stored snippet object."""
        if isinstance(snippet, WaveformSnippet):
            for spec in WaveformSnippet.param_specs():
                w = self._param_controls.get(spec.key)
                val = getattr(snippet, spec.key, None)
                if w is not None and val is not None:
                    self._set_control_value(w, val)
        elif isinstance(snippet, BeatSnippet):
            for spec in type(snippet.rhythm).param_specs():
                w = self._param_controls.get(spec.key)
                val = getattr(snippet.rhythm, spec.key, None)
                if w is not None and val is not None:
                    self._set_control_value(w, val)
            for spec in type(snippet.pos).param_specs():
                w = self._param_controls.get(spec.key)
                val = getattr(snippet.pos, spec.key, None)
                if w is not None and val is not None:
                    self._set_control_value(w, val)

    # ------------------------------------------------------------------ helpers

    def _current_span(self) -> tuple[float, float]:
        start = self._span_start.value()
        dur = max(0.01, self._span_dur.value())
        return (start, start + dur)

    def set_span_from_selection(self) -> None:
        """Called externally when the timeline selection changes."""
        self._use_selection_span()
