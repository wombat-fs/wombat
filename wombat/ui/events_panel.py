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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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
        self._build_ui()
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
        start_row.addWidget(QLabel("Start time (s):"))
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, 86400.0)
        self._start_spin.setDecimals(3)
        self._start_spin.setSingleStep(0.5)
        start_row.addWidget(self._start_spin)
        slay.addLayout(start_row)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Duration (ms, 0 = default):"))
        self._dur_spin = QSpinBox()
        self._dur_spin.setRange(0, 600_000)
        self._dur_spin.setSingleStep(1000)
        self._dur_spin.setValue(0)
        dur_row.addWidget(self._dur_spin)
        slay.addLayout(dur_row)

        self._apply_btn = QPushButton("Apply event")
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.setEnabled(False)
        slay.addWidget(self._apply_btn)

        root.addWidget(settings_box)

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
            # Find longest matching prefix (skip empty prefix for now)
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

        # Render groups in declared order
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
        if self._library and name in self._library.events:
            ev = self._library.events[name]
            lines = [f"<b>{name}</b>", "<br>Default params:"]
            for k, v in ev.default_params.items():
                lines.append(f"&nbsp;&nbsp;{k}: {v}")
            lines.append(f"<br>Steps: {len(ev.steps)}")
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

        # Optional duration override
        dur_override = self._dur_spin.value()
        param_overrides = {}
        if dur_override > 0:
            param_overrides["duration_ms"] = dur_override

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

        self._editor.apply_event_layers(insertions, description=f"Apply event: {name}")

    # ------------------------------------------------------------------ timeline sync

    def sync_playhead(self, position_s: float) -> None:
        """Called by main window when the playhead moves; populates start time."""
        self._start_spin.setValue(position_s)
