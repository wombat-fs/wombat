"""ScriptingMode — pluggable authoring mode abstraction.

Phase 4: DefaultMode only (straight passthrough to editor.add_action).
Phase 9: AlternatingMode, RecordingMode, etc. slot in here without
touching the timeline or EditorController.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wombat.app.editor import EditorController


class ScriptingMode(ABC):
    @abstractmethod
    def add_point(self, editor: EditorController, at: float, pos: int) -> None: ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


class DefaultMode(ScriptingMode):
    def add_point(self, editor: EditorController, at: float, pos: int) -> None:
        editor.add_action(at, pos)
