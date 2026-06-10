from PySide6.QtCore import QByteArray, QSettings


class AppSettings:
    _ORG = "Wombat"
    _APP = "Wombat"

    def __init__(self) -> None:
        self._qs = QSettings(self._ORG, self._APP)

    def save_geometry(self, data: QByteArray) -> None:
        self._qs.setValue("window/geometry", data)

    def load_geometry(self) -> QByteArray | None:
        v = self._qs.value("window/geometry")
        return v if isinstance(v, QByteArray) else None

    def save_dock_state(self, data: QByteArray) -> None:
        self._qs.setValue("window/dockState", data)

    def load_dock_state(self) -> QByteArray | None:
        v = self._qs.value("window/dockState")
        return v if isinstance(v, QByteArray) else None
