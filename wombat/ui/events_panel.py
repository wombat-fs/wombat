"""EventsPanel — load event_definitions.yml, list events, apply at a span.

Dock widget wired alongside Channels/Layers and Snippets.
Layout:
  [Load event definitions...] [path display]
  [event list — groups as section headers, events as rows]
  ---- Apply settings ----
  Start time (s): [spinbox]   Duration override (ms): [spinbox or -1=use default]
  [Apply to timeline selection] [Apply]
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wombat.app.editor import EditorController
from wombat.domain.events.apply import translate_event
from wombat.domain.events.model import EventLibrary
from wombat.domain.events.yaml_loader import load_event_library
from wombat.ui.time_spinbox import TimecodeSpinBox

log = logging.getLogger(__name__)

_DEFAULT_YAML_PATH = str(
    Path(__file__).parent.parent.parent
    / "funscript-tools" / "config.event_definitions.yml"
)


class EventsPanel(QWidget):
    def __init__(self, editor: EditorController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editor = editor
        self._library: EventLibrary | None = None
        self._yaml_path: str = ""
        # When editing an existing event layer: holds its group_id; None = fresh apply mode
        self._editing_group_id: str | None = None
        self._syncing: bool = False
        self._param_spins: dict[str, QSpinBox | QDoubleSpinBox] = {}
        self._build_ui()
        self._connect_editor()
        self._try_load_default()

    # ------------------------------------------------------------------ build UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Load row
        load_row = QHBoxLayout()
        self._load_btn = QPushButton("Load event definitions…")
        self._load_btn.clicked.connect(self._on_load)
        self._path_label = QLabel("(none)")
        self._path_label.setWordWrap(False)
        self._path_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        load_row.addWidget(self._load_btn)
        load_row.addWidget(self._path_label, stretch=1)
        root.addLayout(load_row)

        # Splitter: event list (top) + description (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._event_list = QListWidget()
        self._event_list.currentItemChanged.connect(self._on_event_selected)
        splitter.addWidget(self._event_list)

        self._desc_view = QTextEdit()
        self._desc_view.setReadOnly(True)
        self._desc_view.setMaximumHeight(90)
        self._desc_view.setPlaceholderText("Select an event to see its default parameters.")
        splitter.addWidget(self._desc_view)
        splitter.setSizes([250, 90])

        root.addWidget(splitter, stretch=1)

        # Apply settings
        settings_box = QGroupBox("Apply settings")
        slay = QVBoxLayout(settings_box)

        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("Start time:"))
        self._start_spin = TimecodeSpinBox()
        self._start_spin.setRange(0.0, 86400.0)
        self._start_spin.setDecimals(3)
        self._start_spin.setSingleStep(0.5)
        start_row.addWidget(self._start_spin)
        slay.addLayout(start_row)

        # Dynamic param overrides — rebuilt when event selection changes.
        # Each default_param key gets its own spinbox; 0 / 0.0 means "use event default".
        self._params_inner = QWidget()
        self._params_form = QFormLayout(self._params_inner)
        self._params_form.setContentsMargins(0, 2, 0, 2)
        self._params_form.setSpacing(3)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._params_inner)
        scroll.setMaximumHeight(200)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        slay.addWidget(scroll)

        self._apply_btn = QPushButton("Apply event")
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.setEnabled(False)
        slay.addWidget(self._apply_btn)

        self._cancel_update_btn = QPushButton("Cancel update")
        self._cancel_update_btn.clicked.connect(self._exit_update_mode)
        self._cancel_update_btn.setVisible(False)
        slay.addWidget(self._cancel_update_btn)

        root.addWidget(settings_box)

    # ------------------------------------------------------------------ editor signals

    def _connect_editor(self) -> None:
        self._editor.layer_structure_changed.connect(self._sync_active_layer)
        self._editor.selection_changed.connect(self._sync_active_layer)

    @Slot()
    def _sync_active_layer(self) -> None:
        """Detect if the active layer is an event layer and switch to update mode."""
        if self._syncing:
            return
        self._syncing = True
        try:
            layer = self._editor.active_layer
            if layer is None:
                self._exit_update_mode()
                return
            group_id = getattr(layer, "event_group_id", None)
            if group_id is None:
                self._exit_update_mode()
                return
            self._load_from_layer(layer, group_id)
        finally:
            self._syncing = False

    def _load_from_layer(self, layer: object, group_id: str) -> None:
        if self._library is None:
            return
        event_name = getattr(layer, "event_name", None)
        if not event_name or event_name not in self._library.events:
            return
        start_ms = getattr(layer, "event_start_ms", None) or 0.0
        param_overrides = getattr(layer, "event_param_overrides", {}) or {}

        # Select the event in the list
        for i in range(self._event_list.count()):
            item = self._event_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == event_name:
                self._event_list.setCurrentItem(item)
                break

        self._start_spin.setValue(start_ms / 1000.0)
        for key, spin in self._param_spins.items():
            if key in param_overrides:
                spin.setValue(param_overrides[key])

        self._editing_group_id = group_id
        self._apply_btn.setText("Update event")
        self._cancel_update_btn.setVisible(True)

    def _exit_update_mode(self) -> None:
        if self._editing_group_id is None:
            return
        self._editing_group_id = None
        self._apply_btn.setText("Apply event")
        self._cancel_update_btn.setVisible(False)

    def _refresh_params(self, event) -> None:
        """Rebuild the param spinboxes for the given EventDefinition (or clear if None)."""
        while self._params_form.rowCount() > 0:
            self._params_form.removeRow(0)
        self._param_spins.clear()
        if event is None:
            return
        for key, default_val in event.default_params.items():
            if isinstance(default_val, float):
                spin: QSpinBox | QDoubleSpinBox = QDoubleSpinBox()
                spin.setRange(0.0, 1000.0)
                spin.setDecimals(3)
                spin.setSingleStep(0.05)
                spin.setSpecialValueText("(default)")
            else:
                spin = QSpinBox()
                spin.setRange(0, 600_000)
                spin.setSingleStep(500 if "_ms" in key else 1)
                spin.setSpecialValueText("(default)")
            spin.setValue(0)
            self._params_form.addRow(f"{key}  (default: {default_val}):", spin)
            self._param_spins[key] = spin

    # ------------------------------------------------------------------ load

    def _try_load_default(self) -> None:
        p = Path(_DEFAULT_YAML_PATH)
        if p.exists():
            self._do_load(str(p))

    @Slot()
    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load event definitions", _DEFAULT_YAML_PATH,
            "YAML files (*.yml *.yaml);;All files (*)"
        )
        if path:
            self._do_load(path)

    def _do_load(self, path: str) -> None:
        try:
            lib = load_event_library(path)
        except Exception as exc:
            log.error("Failed to load event definitions from %r: %s", path, exc)
            self._path_label.setText(f"Error: {exc}")
            return
        self._library = lib
        self._yaml_path = path
        self._path_label.setText(Path(path).name)
        self._populate_list()

    def _populate_list(self) -> None:
        if self._library is None:
            return
        self._event_list.clear()
        lib = self._library

        # Build prefix → group_name map
        prefix_to_group: dict[str, str] = {}
        for g in lib.groups:
            prefix_to_group[g.prefix] = g.name

        # Group events by their matching prefix
        grouped: dict[str, list[str]] = {}
        ungrouped: list[str] = []
        for name in sorted(lib.events):
            matched = False
            for prefix, gname in sorted(prefix_to_group.items(), key=lambda x: -len(x[0])):
                if prefix and name.startswith(prefix):
                    grouped.setdefault(gname, []).append(name)
                    matched = True
                    break
            if not matched:
                ungrouped.append(name)

        def add_section(title: str, names: list[str]) -> None:
            if not names:
                return
            header = QListWidgetItem(f"── {title} ──")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self._event_list.addItem(header)
            for n in sorted(names):
                item = QListWidgetItem(f"  {n}")
                item.setData(Qt.ItemDataRole.UserRole, n)
                self._event_list.addItem(item)

        rendered_groups: set[str] = set()
        for g in lib.groups:
            gname = g.name
            if gname in grouped and gname not in rendered_groups:
                add_section(gname, grouped[gname])
                rendered_groups.add(gname)

        add_section("General", ungrouped)

    # ------------------------------------------------------------------ selection

    @Slot()
    def _on_event_selected(self, current: QListWidgetItem | None, _: object) -> None:
        if current is None:
            self._apply_btn.setEnabled(False)
            self._desc_view.clear()
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if name is None:
            self._apply_btn.setEnabled(False)
            self._desc_view.clear()
            return
        self._apply_btn.setEnabled(True)
        # If user picks a different event, exit update mode
        if not self._syncing and self._editing_group_id is not None:
            active_layer = self._editor.active_layer
            active_event = getattr(active_layer, "event_name", None) if active_layer else None
            if name != active_event:
                self._exit_update_mode()
        if self._library and name in self._library.events:
            ev = self._library.events[name]
            self._refresh_params(ev)
            lines = [f"<b>{name}</b>", f"Steps: {len(ev.steps)}"]
            self._desc_view.setHtml("<br>".join(lines))

    # ------------------------------------------------------------------ apply

    @Slot()
    def _on_apply(self) -> None:
        if self._library is None:
            return
        item = self._event_list.currentItem()
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if name is None or name not in self._library.events:
            return

        event = self._library.events[name]
        start_ms = self._start_spin.value() * 1000.0

        param_overrides: dict = {}
        for key, spin in self._param_spins.items():
            v = spin.value()
            if v != 0 and v != 0.0:
                param_overrides[key] = float(v) if isinstance(spin, QDoubleSpinBox) else int(v)

        if self._editing_group_id is not None:
            self._editor.update_event_layers(
                self._editing_group_id,
                event,
                self._library,
                start_ms,
                param_overrides or None,
                event_name=name,
            )
            # layer_structure_changed will fire and _sync_active_layer will
            # re-enter update mode with the new group_id automatically.
            return

        # Fresh apply
        try:
            insertions = translate_event(
                event, self._library, start_ms,
                param_overrides=param_overrides or None,
                group=name,
            )
        except Exception as exc:
            log.error("translate_event failed: %s", exc)
            return

        if not insertions:
            log.warning("Event %r produced no insertions (check channel names)", name)
            return

        self._editor.apply_event_layers(
            insertions,
            description=f"Apply event: {name}",
            event_name=name,
            event_start_ms=start_ms,
            event_param_overrides=param_overrides or None,
        )

    # ------------------------------------------------------------------ timeline sync

    def sync_playhead(self, position_s: float) -> None:
        """Called by main window when the playhead moves; populates start time."""
        self._start_spin.setValue(position_s)
