"""Preferences dialog — user-editable application settings."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from wombat.settings import AppSettings


class PreferencesDialog(QDialog):
    """Minimal settings dialog.

    Changes take effect on OK; Cancel discards them.  The caller is
    responsible for propagating saved values (e.g. updating synthesis
    params, snap flag) after ``exec()`` returns ``Accepted``.
    """

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(340)
        self._settings = settings
        self._build_ui()
        self._load()

    # ----------------------------------------------------------------- build

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Editing ---
        edit_group = QGroupBox("Editing")
        edit_form = QFormLayout(edit_group)

        self._snap = QCheckBox()
        self._snap.setToolTip(
            "When enabled, actions are snapped to the nearest video frame boundary."
        )
        edit_form.addRow("Snap to frame by default", self._snap)

        layout.addWidget(edit_group)

        # --- Synthesis ---
        synth_group = QGroupBox("Synthesis")
        synth_form = QFormLayout(synth_group)

        self._synth_hz = QSpinBox()
        self._synth_hz.setRange(10, 1000)
        self._synth_hz.setSuffix(" Hz")
        self._synth_hz.setToolTip(
            "Dense sampling rate used inside layer fade windows.\n"
            "Higher values → smoother fades, slower synthesis."
        )
        synth_form.addRow("Fade resolution", self._synth_hz)

        self._epsilon = QDoubleSpinBox()
        self._epsilon.setRange(0.0, 10.0)
        self._epsilon.setSingleStep(0.1)
        self._epsilon.setDecimals(2)
        self._epsilon.setToolTip(
            "RDP simplification tolerance (position units, 0–100).\n"
            "Higher values → fewer output points in fade regions.\n"
            "0 = disabled."
        )
        synth_form.addRow("Simplify epsilon", self._epsilon)

        layout.addWidget(synth_group)

        # --- Keybindings hint ---
        kb_group = QGroupBox("Keybindings")
        kb_layout = QVBoxLayout(kb_group)
        from wombat import keybindings
        kb_path = keybindings.config_path()
        hint = QLabel(
            f"Edit <b>keybindings.json</b> to customise shortcuts.<br>"
            f'<small style="color:#888;">{kb_path}</small>'
        )
        hint.setWordWrap(True)
        kb_layout.addWidget(hint)

        open_btn = QPushButton("Open keybindings file…")
        open_btn.clicked.connect(self._open_keybindings)
        kb_layout.addWidget(open_btn)

        layout.addWidget(kb_group)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ----------------------------------------------------------------- load/save

    def _load(self) -> None:
        self._snap.setChecked(self._settings.load_snap_to_frame())
        self._synth_hz.setValue(int(self._settings.load_synthesis_hz()))
        self._epsilon.setValue(self._settings.load_simplify_epsilon())

    def _save_and_accept(self) -> None:
        self._settings.save_snap_to_frame(self._snap.isChecked())
        self._settings.save_synthesis_hz(float(self._synth_hz.value()))
        self._settings.save_simplify_epsilon(self._epsilon.value())
        self.accept()

    # ----------------------------------------------------------------- actions

    def _open_keybindings(self) -> None:
        from wombat import keybindings
        path = keybindings.config_path()
        keybindings.write_template()  # create if missing
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
