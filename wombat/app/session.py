"""Session — minimal current-document holder (player + channels).

Phase 5 will promote this into a full Project with save/load, metadata, etc.
Keep it thin.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from wombat.domain.channel import Channel
from wombat.playback.player import VideoPlayer


@dataclass
class Session:
    player: VideoPlayer
    channels: list[Channel] = field(default_factory=list)
