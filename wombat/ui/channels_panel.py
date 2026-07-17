"""ChannelsPanel — channel→layer tree dock.

Top level: one item per channel (enabled checkbox, active indicator, name).
Second level: one item per layer (enabled checkbox, blend badge, active indicator, name),
shown top-of-stack first and the base last (image/audio-editor convention).

Channel ops drive Project directly; layer ops drive EditorController.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from wombat.app.editor import EditorController
    from wombat.app.project import Project
    from wombat.domain.channel import BlendMode

# Channel presets — names match funscript-tools' output axes so its event YAMLs and
# generated files map onto Wombat channels directly (underscores, not hyphens).
_PRESET_NAMES = [
    "orig", "alpha", "beta", "volume",
    "frequency", "pulse_frequency", "pulse_width", "pulse_rise_time",
]

_ACTIVE_CH_COLOR = QColor("#00a8e8")
_INACTIVE_COLOR = QColor("#aaaaaa")
_ACTIVE_LAYER_COLOR = QColor("#00e8a8")
_BLEND_OVERRIDE = "OVR"
_BLEND_ADDITIVE = "ADD"
_BLEND_MULTIPLY = "MUL"
# Keyed by BlendMode's string value (str-enum hashes equal to its value).
_BLEND_BADGES = {
    "override": _BLEND_OVERRIDE,
    "additive": _BLEND_ADDITIVE,
    "multiply": _BLEND_MULTIPLY,
}

# TreeWidgetItem user roles
_ROLE_CH_IDX = Qt.ItemDataRole.UserRole
_ROLE_LAYER_IDX = Qt.ItemDataRole.UserRole + 1


class ChannelsPanel(QWidget):
    def __init__(
        self,
        project: Project,
        editor: EditorController | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._editor = editor
        self._refreshing = False

        # Channel toolbar
        self._btn_add_ch = QPushButton("+")
        self._btn_add_ch.setToolTip("Add channel")
        self._btn_add_ch.setFixedWidth(28)
        btn_import = QPushButton("Import…")
        btn_import.setToolTip("Import funscript as channel")
        self._btn_remove_ch = QPushButton("−")
        self._btn_remove_ch.setToolTip("Remove selected channel")
        self._btn_remove_ch.setFixedWidth(28)
        self._btn_ch_up = QPushButton("↑")
        self._btn_ch_up.setToolTip("Move channel up")
        self._btn_ch_up.setFixedWidth(28)
        self._btn_ch_down = QPushButton("↓")
        self._btn_ch_down.setToolTip("Move channel down")
        self._btn_ch_down.setFixedWidth(28)

        ch_row = QHBoxLayout()
        ch_row.setContentsMargins(0, 0, 0, 0)
        ch_row.addWidget(self._btn_add_ch)
        ch_row.addWidget(btn_import)
        ch_row.addWidget(self._btn_remove_ch)
        ch_row.addStretch()
        ch_row.addWidget(self._btn_ch_up)
        ch_row.addWidget(self._btn_ch_down)

        # Layer toolbar
        self._btn_add_layer = QPushButton("+ Layer")
        self._btn_add_layer.setToolTip("Add layer to active channel")
        self._btn_dup_layer = QPushButton("Dup")
        self._btn_dup_layer.setToolTip("Duplicate selected layer")
        self._btn_remove_layer = QPushButton("− Layer")
        self._btn_remove_layer.setToolTip("Remove selected layer")
        self._btn_layer_up = QPushButton("↑")
        self._btn_layer_up.setFixedWidth(28)
        self._btn_layer_down = QPushButton("↓")
        self._btn_layer_down.setFixedWidth(28)

        layer_row = QHBoxLayout()
        layer_row.setContentsMargins(0, 0, 0, 0)
        layer_row.addWidget(self._btn_add_layer)
        layer_row.addWidget(self._btn_dup_layer)
        layer_row.addWidget(self._btn_remove_layer)
        layer_row.addStretch()
        layer_row.addWidget(self._btn_layer_up)
        layer_row.addWidget(self._btn_layer_down)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setAlternatingRowColors(False)
        self._tree.setIndentation(16)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.addLayout(ch_row)
        layout.addLayout(layer_row)
        layout.addWidget(self._tree)

        # channel buttons
        self._btn_add_ch.clicked.connect(self._add_channel)
        btn_import.clicked.connect(self._import_channel)
        self._btn_remove_ch.clicked.connect(self._remove_channel)
        self._btn_ch_up.clicked.connect(self._move_ch_up)
        self._btn_ch_down.clicked.connect(self._move_ch_down)

        # layer buttons
        self._btn_add_layer.clicked.connect(self._add_layer)
        self._btn_dup_layer.clicked.connect(self._dup_layer)
        self._btn_remove_layer.clicked.connect(self._remove_layer)
        self._btn_layer_up.clicked.connect(self._move_layer_up)
        self._btn_layer_down.clicked.connect(self._move_layer_down)

        self._tree.currentItemChanged.connect(self._on_current_changed)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        project.channels_changed.connect(self._refresh)
        project.active_changed.connect(self._on_active_channel_changed)
        if editor is not None:
            editor.layer_structure_changed.connect(self._refresh)

        self._refresh()

    # ----------------------------------------------------------------- project swap

    def set_project(self, project: Project) -> None:
        try:
            self._project.channels_changed.disconnect(self._refresh)
            self._project.active_changed.disconnect(self._on_active_channel_changed)
        except RuntimeError:
            pass
        self._project = project
        project.channels_changed.connect(self._refresh)
        project.active_changed.connect(self._on_active_channel_changed)
        self._refresh()

    def set_editor(self, editor: EditorController) -> None:
        if self._editor is not None:
            try:
                self._editor.layer_structure_changed.disconnect(self._refresh)
            except RuntimeError:
                pass
        self._editor = editor
        editor.layer_structure_changed.connect(self._refresh)

    # ----------------------------------------------------------------- tree build

    @Slot()
    def _refresh(self) -> None:
        self._refreshing = True
        self._tree.blockSignals(True)

        # Preserve expanded state
        expanded: set[int] = set()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is not None and item.isExpanded():
                expanded.add(i)

        # If the current selection is a channel row, restore to channel row (not a layer)
        prev = self._tree.currentItem()
        prev_is_channel = prev is not None and prev.data(0, _ROLE_LAYER_IDX) == -1

        self._tree.clear()

        active_ch = self._project.active_index
        active_li = -1 if prev_is_channel else (
            self._editor.active_layer_index if self._editor else 0
        )

        for ci, ch in enumerate(self._project.channels):
            ch_item = QTreeWidgetItem([ch.name])
            ch_item.setFlags(
                ch_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
            )
            ch_item.setCheckState(
                0,
                Qt.CheckState.Checked if ch.enabled else Qt.CheckState.Unchecked,
            )
            color = _ACTIVE_CH_COLOR if ci == active_ch else _INACTIVE_COLOR
            ch_item.setForeground(0, color)
            ch_item.setData(0, _ROLE_CH_IDX, ci)
            ch_item.setData(0, _ROLE_LAYER_IDX, -1)
            self._tree.addTopLevelItem(ch_item)

            # Display top-of-stack (highest index, the overriding layer) first and
            # the base last, matching image/audio editors. _ROLE_LAYER_IDX always
            # stores the true model index, so layer logic is unaffected by view order.
            for li in range(len(ch.layers) - 1, -1, -1):
                layer = ch.layers[li]
                blend_badge = _BLEND_BADGES.get(layer.blend, _BLEND_OVERRIDE)
                label = f"  {blend_badge}  {layer.name}"
                l_item = QTreeWidgetItem([label])
                l_item.setFlags(
                    l_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                l_item.setCheckState(
                    0,
                    Qt.CheckState.Checked if layer.enabled else Qt.CheckState.Unchecked,
                )
                is_active_layer = (ci == active_ch) and (li == active_li)
                l_color = _ACTIVE_LAYER_COLOR if is_active_layer else _INACTIVE_COLOR
                l_item.setForeground(0, l_color)
                l_item.setData(0, _ROLE_CH_IDX, ci)
                l_item.setData(0, _ROLE_LAYER_IDX, li)
                ch_item.addChild(l_item)

            if ci in expanded or ci == active_ch:
                ch_item.setExpanded(True)

        # Restore current selection
        self._select_active_item(active_ch, active_li)

        self._tree.blockSignals(False)
        self._refreshing = False
        self._update_button_states()

    def _select_channel_row(self, ch_idx: int) -> None:
        """Select the channel row for ch_idx without triggering further refreshes."""
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is not None and item.data(0, _ROLE_CH_IDX) == ch_idx:
                self._tree.blockSignals(True)
                self._tree.setCurrentItem(item)
                self._tree.blockSignals(False)
                self._update_button_states()
                return

    def _select_active_item(self, ch_idx: int, layer_idx: int) -> None:
        for i in range(self._tree.topLevelItemCount()):
            ch_item = self._tree.topLevelItem(i)
            if ch_item is None:
                continue
            if ch_item.data(0, _ROLE_CH_IDX) == ch_idx:
                # Try to find the active layer item
                for j in range(ch_item.childCount()):
                    l_item = ch_item.child(j)
                    if l_item and l_item.data(0, _ROLE_LAYER_IDX) == layer_idx:
                        self._tree.setCurrentItem(l_item)
                        return
                self._tree.setCurrentItem(ch_item)
                return

    def _update_button_states(self) -> None:
        has_ch = len(self._project.channels) > 0
        has_editor = self._editor is not None
        item = self._tree.currentItem()
        is_ch = item is not None and item.data(0, _ROLE_LAYER_IDX) == -1
        is_layer = item is not None and item.data(0, _ROLE_LAYER_IDX) >= 0

        ci = item.data(0, _ROLE_CH_IDX) if item else -1
        li = item.data(0, _ROLE_LAYER_IDX) if item else -1
        n_ch = len(self._project.channels)
        n_layers = len(self._project.channels[ci].layers) if 0 <= ci < n_ch else 0

        self._btn_remove_ch.setEnabled(has_ch and is_ch)
        self._btn_ch_up.setEnabled(is_ch and ci > 0)
        self._btn_ch_down.setEnabled(is_ch and 0 <= ci < n_ch - 1)

        self._btn_add_layer.setEnabled(has_editor and has_ch)
        self._btn_dup_layer.setEnabled(has_editor and is_layer)
        self._btn_remove_layer.setEnabled(has_editor and is_layer and n_layers > 1)
        # List is top-of-stack first, so visual "up" = toward higher model index.
        self._btn_layer_up.setEnabled(has_editor and is_layer and 0 <= li < n_layers - 1)
        self._btn_layer_down.setEnabled(has_editor and is_layer and li > 0)

    # ----------------------------------------------------------------- signals

    @Slot(object, object)
    def _on_current_changed(
        self, current: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None
    ) -> None:
        if self._refreshing or current is None:
            return
        ci = current.data(0, _ROLE_CH_IDX)
        li = current.data(0, _ROLE_LAYER_IDX)
        if not (0 <= ci < len(self._project.channels)):
            return
        if ci != self._project.active_index:
            self._project.set_active(ci)
        if li >= 0 and self._editor is not None:
            self._editor.set_active_layer_index(li)
        self._update_button_states()

    @Slot(int)
    def _on_active_channel_changed(self, _index: int) -> None:
        self._refresh()

    @Slot(QTreeWidgetItem)
    def _on_item_changed(self, item: QTreeWidgetItem) -> None:
        if self._refreshing:
            return
        ci = item.data(0, _ROLE_CH_IDX)
        li = item.data(0, _ROLE_LAYER_IDX)
        if not (0 <= ci < len(self._project.channels)):
            return
        enabled = item.checkState(0) == Qt.CheckState.Checked
        ch = self._project.channels[ci]
        if li == -1:
            if enabled != ch.enabled:
                ch.enabled = enabled
        else:
            if 0 <= li < len(ch.layers) and self._editor is not None:
                if enabled != ch.layers[li].enabled:
                    self._editor.set_layer_enabled(li, enabled)

    @Slot(QTreeWidgetItem, int)
    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        ci = item.data(0, _ROLE_CH_IDX)
        li = item.data(0, _ROLE_LAYER_IDX)
        if not (0 <= ci < len(self._project.channels)):
            return
        ch = self._project.channels[ci]
        if li == -1:
            old_name = ch.name
            new_name, ok = QInputDialog.getText(
                self, "Rename Channel", "Channel name:", text=old_name
            )
            if ok and new_name.strip() and new_name.strip() != old_name:
                self._project.rename_channel(ci, new_name.strip())
        elif 0 <= li < len(ch.layers) and self._editor is not None:
            old_name = ch.layers[li].name
            new_name, ok = QInputDialog.getText(
                self, "Rename Layer", "Layer name:", text=old_name
            )
            if ok and new_name.strip() and new_name.strip() != old_name:
                self._editor.rename_layer(li, new_name.strip())

    @Slot(object)
    def _on_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None or self._editor is None:
            return
        ci = item.data(0, _ROLE_CH_IDX)
        li = item.data(0, _ROLE_LAYER_IDX)
        if not (0 <= ci < len(self._project.channels)) or li < 0:
            return
        ch = self._project.channels[ci]
        from wombat.domain.channel import BlendMode
        layer = ch.layers[li] if 0 <= li < len(ch.layers) else None
        if layer is None:
            return

        menu = QMenu(self)

        # Blend mode picker — checkable, current mode marked.
        blend_menu = menu.addMenu("Blend mode")
        blend_actions: dict[object, BlendMode] = {}
        for mode, label in (
            (BlendMode.OVERRIDE, "Override"),
            (BlendMode.ADDITIVE, "Additive"),
            (BlendMode.MULTIPLY, "Multiply"),
        ):
            act = blend_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(layer.blend == mode)
            blend_actions[act] = mode

        menu.addSeparator()
        merge_action = menu.addAction("Merge Down")
        merge_action.setToolTip("Bake this layer into the layer below it in the stack")
        merge_action.setEnabled(li >= 1)

        menu.addSeparator()
        delete_action = menu.addAction("Delete Layer")
        delete_action.setEnabled(len(ch.layers) > 1)

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen in blend_actions:
            new_blend = blend_actions[chosen]
            if new_blend != layer.blend:
                self._editor.set_blend(li, new_blend)
        elif chosen is merge_action and li >= 1:
            self._editor.merge_layer_down(li)
        elif chosen is delete_action and len(ch.layers) > 1:
            self._editor.remove_layer(li)

    # ----------------------------------------------------------------- channel buttons

    @Slot()
    def _add_channel(self) -> None:
        menu = QMenu(self)
        for name in _PRESET_NAMES:
            menu.addAction(name)
        menu.addSeparator()
        custom_action = menu.addAction("Custom…")
        action = menu.exec(self.mapToGlobal(self._btn_add_ch.rect().bottomLeft()))
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
        from pathlib import Path
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Funscript", "",
            "Funscript Files (*.funscript);;All Files (*)",
        )
        if not path:
            return
        # Try to parse the axis name from the filename.
        # Primary: exact base match  e.g. "clip.volume.funscript" + media "clip.mp4" → "volume"
        # Fallback: extract suffix after last dot in stem e.g. "MyClip.volume.funscript" → "volume"
        name: str | None = None
        stem = Path(path).stem   # e.g. "Intense Hypnos.volume"
        if self._project.media_path:
            from wombat.app.naming import parse_channel_name
            base = Path(self._project.media_path).stem
            parsed = parse_channel_name(Path(path).name, base)
            if parsed is not None:
                name = parsed if parsed else "orig"
        if name is None and "." in stem:
            # No media match — use the part after the last dot as the channel name
            name = stem.rsplit(".", 1)[-1]
        self._project.import_funscript(path, name=name)
        self._project.set_active(len(self._project.channels) - 1)

    @Slot()
    def _remove_channel(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        ci = item.data(0, _ROLE_CH_IDX)
        if 0 <= ci < len(self._project.channels):
            self._project.remove_channel(ci)

    @Slot()
    def _move_ch_up(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        ci = item.data(0, _ROLE_CH_IDX)
        if ci > 0:
            self._project.move_channel(ci, ci - 1)
            self._select_channel_row(ci - 1)

    @Slot()
    def _move_ch_down(self) -> None:
        item = self._tree.currentItem()
        if item is None:
            return
        ci = item.data(0, _ROLE_CH_IDX)
        if 0 <= ci < len(self._project.channels) - 1:
            self._project.move_channel(ci, ci + 1)
            self._select_channel_row(ci + 1)

    # ----------------------------------------------------------------- layer buttons

    def _active_ci_li(self) -> tuple[int, int]:
        """Return (channel_idx, layer_idx) for the currently selected item."""
        item = self._tree.currentItem()
        if item is None:
            return (
                self._project.active_index,
                self._editor.active_layer_index if self._editor else 0,
            )
        ci = item.data(0, _ROLE_CH_IDX)
        li = item.data(0, _ROLE_LAYER_IDX)
        if li == -1:
            li = 0
        return ci, li

    @Slot()
    def _add_layer(self) -> None:
        if self._editor is None:
            return
        self._editor.add_layer()

    @Slot()
    def _dup_layer(self) -> None:
        if self._editor is None:
            return
        _ci, li = self._active_ci_li()
        self._editor.duplicate_layer(li)

    @Slot()
    def _remove_layer(self) -> None:
        if self._editor is None:
            return
        _ci, li = self._active_ci_li()
        self._editor.remove_layer(li)

    @Slot()
    def _move_layer_up(self) -> None:
        """Move the layer up in the list — i.e. toward the top of the stack (higher index)."""
        if self._editor is None:
            return
        ch_idx, li = self._active_ci_li()
        if 0 <= ch_idx < len(self._project.channels):
            n = len(self._project.channels[ch_idx].layers)
            if li < n - 1:
                self._editor.reorder_layer(li, li + 1)

    @Slot()
    def _move_layer_down(self) -> None:
        """Move the layer down in the list — i.e. toward the base (lower index)."""
        if self._editor is None:
            return
        _ci, li = self._active_ci_li()
        if li > 0:
            self._editor.reorder_layer(li, li - 1)
