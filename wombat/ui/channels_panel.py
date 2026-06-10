"""ChannelsPanel — right-dock channel list.

Shows one row per channel with an enabled checkbox, active indicator,
and buttons for add / import / remove / rename / reorder.

The panel drives the Project only — activation flows via project signals
back to MainWindow → EditorController.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from wombat.app.project import Project

_PRESET_NAMES = ["orig", "alpha", "beta", "volume", "frequency", "pulse-width", "pulse-rise"]
_ACTIVE_COLOR = QColor("#00a8e8")
_INACTIVE_COLOR = QColor("#aaaaaa")


class ChannelsPanel(QWidget):
    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project

        # Toolbar buttons
        self._btn_add = QPushButton("+")
        self._btn_add.setToolTip("Add channel")
        self._btn_add.setFixedWidth(28)
        btn_import = QPushButton("Import…")
        btn_import.setToolTip("Import funscript as channel")
        self._btn_remove = QPushButton("−")
        self._btn_remove.setToolTip("Remove selected channel")
        self._btn_remove.setFixedWidth(28)
        self._btn_up = QPushButton("↑")
        self._btn_up.setToolTip("Move channel up")
        self._btn_up.setFixedWidth(28)
        self._btn_down = QPushButton("↓")
        self._btn_down.setToolTip("Move channel down")
        self._btn_down.setFixedWidth(28)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(btn_import)
        btn_row.addWidget(self._btn_remove)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_up)
        btn_row.addWidget(self._btn_down)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addLayout(btn_row)
        layout.addWidget(self._list)

        self._btn_add.clicked.connect(self._add_channel)
        btn_import.clicked.connect(self._import_channel)
        self._btn_remove.clicked.connect(self._remove_channel)
        self._btn_up.clicked.connect(self._move_up)
        self._btn_down.clicked.connect(self._move_down)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.itemDoubleClicked.connect(self._on_rename_requested)

        project.channels_changed.connect(self._refresh)
        project.active_changed.connect(self._on_active_changed)
        self._refresh()

    # ----------------------------------------------------------------- project swap

    def set_project(self, project: Project) -> None:
        try:
            self._project.channels_changed.disconnect(self._refresh)
            self._project.active_changed.disconnect(self._on_active_changed)
        except RuntimeError:
            pass
        self._project = project
        project.channels_changed.connect(self._refresh)
        project.active_changed.connect(self._on_active_changed)
        self._refresh()

    # ----------------------------------------------------------------- list management

    @Slot()
    def _refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for i, ch in enumerate(self._project.channels):
            item = QListWidgetItem(ch.name)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            item.setCheckState(
                Qt.CheckState.Checked if ch.enabled else Qt.CheckState.Unchecked
            )
            color = _ACTIVE_COLOR if i == self._project.active_index else _INACTIVE_COLOR
            item.setForeground(color)
            self._list.addItem(item)
        if 0 <= self._project.active_index < self._list.count():
            self._list.setCurrentRow(self._project.active_index)
        self._list.blockSignals(False)
        self._update_button_states()

    def _update_button_states(self) -> None:
        n = len(self._project.channels)
        row = self._list.currentRow()
        self._btn_remove.setEnabled(n > 0 and row >= 0)
        self._btn_up.setEnabled(row > 0)
        self._btn_down.setEnabled(0 <= row < n - 1)

    @Slot(int)
    def _on_row_changed(self, row: int) -> None:
        if row >= 0 and row < len(self._project.channels):
            self._project.set_active(row)
        self._update_button_states()

    @Slot(int)
    def _on_active_changed(self, index: int) -> None:
        self._refresh()

    @Slot(QListWidgetItem)
    def _on_item_changed(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if not (0 <= row < len(self._project.channels)):
            return
        ch = self._project.channels[row]
        enabled = item.checkState() == Qt.CheckState.Checked
        if enabled != ch.enabled:
            ch.enabled = enabled

    @Slot(QListWidgetItem)
    def _on_rename_requested(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if not (0 <= row < len(self._project.channels)):
            return
        old_name = self._project.channels[row].name
        new_name, ok = QInputDialog.getText(
            self, "Rename Channel", "Channel name:", text=old_name
        )
        if ok and new_name.strip() and new_name.strip() != old_name:
            self._project.rename_channel(row, new_name.strip())

    # ----------------------------------------------------------------- buttons

    @Slot()
    def _add_channel(self) -> None:
        menu = QMenu(self)
        for name in _PRESET_NAMES:
            menu.addAction(name)
        menu.addSeparator()
        custom_action = menu.addAction("Custom…")
        action = menu.exec(self.mapToGlobal(self._btn_add.rect().bottomLeft()))
        if action is None:
            return
        if action is custom_action:
            name, ok = QInputDialog.getText(self, "Add Channel", "Channel name:")
            if not ok or not name.strip():
                return
            name = name.strip()
        else:
            name = action.text()
        self._project.add_channel(name)
        self._project.set_active(len(self._project.channels) - 1)

    @Slot()
    def _import_channel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Funscript",
            "",
            "Funscript Files (*.funscript);;All Files (*)",
        )
        if path:
            self._project.import_funscript(path)
            self._project.set_active(len(self._project.channels) - 1)

    @Slot()
    def _remove_channel(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._project.remove_channel(row)

    @Slot()
    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row > 0:
            self._project.move_channel(row, row - 1)

    @Slot()
    def _move_down(self) -> None:
        row = self._list.currentRow()
        n = len(self._project.channels)
        if 0 <= row < n - 1:
            self._project.move_channel(row, row + 1)
