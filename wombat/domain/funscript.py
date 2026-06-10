"""Funscript — file-format DTO.

Separate from Channel (the editable model) so I/O and editing concerns don't mix.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from wombat.domain.action import ActionList


@dataclass
class FunscriptMetadata:
    type: str = "basic"
    title: str = ""
    creator: str = ""
    script_url: str = ""
    video_url: str = ""
    tags: list[str] = field(default_factory=list)
    performers: list[str] = field(default_factory=list)
    description: str = ""
    license: str = ""
    notes: str = ""
    duration: int = 0   # ms, as in the format
    extra: dict = field(default_factory=dict)   # unknown metadata keys, preserved


@dataclass
class Funscript:
    """File-format object. Editing goes through Channel; export goes through this."""

    actions: ActionList
    metadata: FunscriptMetadata = field(default_factory=FunscriptMetadata)
    version: str = "1.0"
    inverted: bool = False
    range_: int = 100
    extra: dict = field(default_factory=dict)   # unknown top-level keys, preserved
