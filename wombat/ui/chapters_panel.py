"""ChaptersPanel — list view for project chapters/bookmarks."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
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
    from wombat.domain.chapter import Chapter
    from wombat.playback.player import VideoPlayer


def _fmt(t: float) -> str:
    m = int(t) // 60
    s = t % 60
    return f"{m}:{s:05.2f}" if m else f"{s:.2f}s"


class ChaptersPanel(QWidget):
    def __init__(self, project: Project, player: VideoPlayer, parent=None) -> None:
        super().__init__(parent)
        self._project = project
        self._player = player
        self._build_ui()
        self._connect(project)
        self._refresh()

    # ----------------------------------------------------------------- build

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        add_btn = QPushButton("Add")
        add_btn.setToolTip("Add chapter at current playhead position")
        add_btn.clicked.connect(self._add_chapter)
        btn_row.addWidget(add_btn)

        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._rename_selected)
        btn_row.addWidget(rename_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(remove_btn)

        layout.addLayout(btn_row)

    # ----------------------------------------------------------------- project swap

    def set_project(self, project: Project) -> None:
        try:
            self._project.chapters_changed.disconnect(self._refresh)
        except RuntimeError:
            pass
        self._project = project
        self._connect(project)
        self._refresh()

    def _connect(self, project: Project) -> None:
        project.chapters_changed.connect(self._refresh)

    # ----------------------------------------------------------------- refresh

    @Slot()
    def _refresh(self) -> None:
        self._list.clear()
        for ch in self._project.chapters:
            label = f"{_fmt(ch.at)}  {ch.name}" if ch.name else _fmt(ch.at)
            if ch.is_range and ch.end is not None:
                label += f" → {_fmt(ch.end)}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self._list.addItem(item)

    # ----------------------------------------------------------------- slots

    @Slot(QListWidgetItem)
    def _on_double_click(self, item: QListWidgetItem) -> None:
        ch: Chapter = item.data(Qt.ItemDataRole.UserRole)
        self._player.seek_exact(ch.at)

    @Slot()
    def _add_chapter(self) -> None:
        t = self._player.logical_time
        name, ok = QInputDialog.getText(
            self, "Add Chapter", f"Name for chapter at {_fmt(t)}:"
        )
        if ok:
            self._project.add_chapter(t, name=name.strip())

    @Slot()
    def _rename_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        ch: Chapter = item.data(Qt.ItemDataRole.UserRole)
        name, ok = QInputDialog.getText(
            self, "Rename Chapter", "New name:", text=ch.name
        )
        if ok:
            self._project.rename_chapter(ch, name.strip())

    @Slot()
    def _remove_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        ch: Chapter = item.data(Qt.ItemDataRole.UserRole)
        self._project.remove_chapter(ch)

    @Slot(object)
    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        ch: Chapter = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        seek_action = menu.addAction(f"Seek to {_fmt(ch.at)}")
        rename_action = menu.addAction("Rename…")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
        if chosen is seek_action:
            self._player.seek_exact(ch.at)
        elif chosen is rename_action:
            name, ok = QInputDialog.getText(self, "Rename Chapter", "New name:", text=ch.name)
            if ok:
                self._project.rename_chapter(ch, name.strip())
        elif chosen is delete_action:
            self._project.remove_chapter(ch)
