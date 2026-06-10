"""Chapter — named time marker or time range stored in a Project."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chapter:
    at: float                   # seconds (point or range start)
    name: str = ""
    end: float | None = None    # None → point marker; float → range chapter

    @property
    def is_range(self) -> bool:
        return self.end is not None

    def __lt__(self, other: Chapter) -> bool:
        return self.at < other.at

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Chapter):
            return NotImplemented
        return self.at == other.at and self.name == other.name and self.end == other.end

    def __hash__(self) -> int:
        return hash((self.at, self.name, self.end))
