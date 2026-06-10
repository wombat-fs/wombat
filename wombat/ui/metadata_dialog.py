"""MetadataDialog — per-channel FunscriptMetadata editor."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from wombat.domain.channel import Channel


class MetadataDialog(QDialog):
    """Edit FunscriptMetadata for a single channel in place."""

    def __init__(self, channel: Channel, parent=None) -> None:
        super().__init__(parent)
        self._channel = channel
        self.setWindowTitle(f"Metadata — {channel.name}")
        self.setMinimumWidth(380)
        self._build_ui()
        self._load()

    # ----------------------------------------------------------------- build

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._title = QLineEdit()
        form.addRow("Title", self._title)

        self._creator = QLineEdit()
        form.addRow("Creator", self._creator)

        self._tags = QLineEdit()
        self._tags.setPlaceholderText("comma-separated")
        form.addRow("Tags", self._tags)

        self._performers = QLineEdit()
        self._performers.setPlaceholderText("comma-separated")
        form.addRow("Performers", self._performers)

        self._description = QPlainTextEdit()
        self._description.setMaximumHeight(70)
        form.addRow("Description", self._description)

        self._license = QLineEdit()
        self._license.setPlaceholderText("e.g. CC BY 4.0")
        form.addRow("License", self._license)

        self._script_url = QLineEdit()
        form.addRow("Script URL", self._script_url)

        self._video_url = QLineEdit()
        form.addRow("Video URL", self._video_url)

        self._notes = QPlainTextEdit()
        self._notes.setMaximumHeight(60)
        form.addRow("Notes", self._notes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ----------------------------------------------------------------- load / save

    def _load(self) -> None:
        m = self._channel.metadata
        self._title.setText(m.title)
        self._creator.setText(m.creator)
        self._tags.setText(", ".join(m.tags))
        self._performers.setText(", ".join(m.performers))
        self._description.setPlainText(m.description)
        self._license.setText(m.license)
        self._script_url.setText(m.script_url)
        self._video_url.setText(m.video_url)
        self._notes.setPlainText(m.notes)

    def _save_and_accept(self) -> None:
        m = self._channel.metadata
        m.title = self._title.text().strip()
        m.creator = self._creator.text().strip()
        m.tags = [t.strip() for t in self._tags.text().split(",") if t.strip()]
        m.performers = [p.strip() for p in self._performers.text().split(",") if p.strip()]
        m.description = self._description.toPlainText().strip()
        m.license = self._license.text().strip()
        m.script_url = self._script_url.text().strip()
        m.video_url = self._video_url.text().strip()
        m.notes = self._notes.toPlainText().strip()
        self.accept()
