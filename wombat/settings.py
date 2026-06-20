from PySide6.QtCore import QByteArray, QSettings


class AppSettings:
    _ORG = "Wombat"
    _APP = "Wombat"

    def __init__(self) -> None:
        self._qs = QSettings(self._ORG, self._APP)

    # ----------------------------------------------------------------- window

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

    # ----------------------------------------------------------------- prefs

    def load_snap_to_frame(self) -> bool:
        v = self._qs.value("prefs/snapToFrame", False)
        return v if isinstance(v, bool) else str(v).lower() == "true"

    def save_snap_to_frame(self, v: bool) -> None:
        self._qs.setValue("prefs/snapToFrame", v)

    def load_snap_to_beats(self) -> bool:
        v = self._qs.value("prefs/snapToBeats", False)
        return v if isinstance(v, bool) else str(v).lower() == "true"

    def save_snap_to_beats(self, v: bool) -> None:
        self._qs.setValue("prefs/snapToBeats", v)

    def load_synthesis_hz(self) -> float:
        try:
            return float(self._qs.value("prefs/synthesisHz", 60.0))
        except (TypeError, ValueError):
            return 60.0

    def save_synthesis_hz(self, v: float) -> None:
        self._qs.setValue("prefs/synthesisHz", float(v))

    def load_simplify_epsilon(self) -> float:
        try:
            return float(self._qs.value("prefs/simplifyEpsilon", 0.5))
        except (TypeError, ValueError):
            return 0.5

    def save_simplify_epsilon(self, v: float) -> None:
        self._qs.setValue("prefs/simplifyEpsilon", float(v))

    def load_beat_binary_path(self) -> str:
        return str(self._qs.value("prefs/beatBinaryPath", "") or "")

    def save_beat_binary_path(self, v: str) -> None:
        self._qs.setValue("prefs/beatBinaryPath", v)

    def load_beat_model_path(self) -> str:
        return str(self._qs.value("prefs/beatModelPath", "") or "")

    def save_beat_model_path(self, v: str) -> None:
        self._qs.setValue("prefs/beatModelPath", v)

    def load_dark_theme(self) -> bool:
        v = self._qs.value("prefs/darkTheme", True)
        return v if isinstance(v, bool) else str(v).lower() != "false"

    def save_dark_theme(self, v: bool) -> None:
        self._qs.setValue("prefs/darkTheme", v)

    def get_synthesis_params(self):
        """Return a SynthesisParams built from stored preferences."""
        from wombat.domain.synthesis import SynthesisParams
        return SynthesisParams(
            resolution_hz=self.load_synthesis_hz(),
            simplify_epsilon=self.load_simplify_epsilon(),
        )
