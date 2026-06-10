"""Channel — editable funscript unit owning a stack of Layers.

Phase 2: synthesize() is identity over the single enabled base layer.
Phase 6 will fold the full stack with blend/span/fade envelopes.

The seam: everything downstream (rendering, export, heatmap) consumes
synthesize(); editing always targets a specific Layer. This is explicit
even while synthesis is identity, so Phase 6 adds no coupling outside here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from wombat.domain.action import ActionList
from wombat.domain.funscript import Funscript, FunscriptMetadata


class BlendMode(Enum):
    OVERRIDE = "override"
    ADDITIVE = "additive"


@dataclass
class Layer:
    actions: ActionList
    name: str = "base"
    enabled: bool = True
    # Envelope — present now, honored in Phase 6:
    blend: BlendMode = BlendMode.OVERRIDE
    span: tuple[float, float] | None = None   # None = whole timeline
    fade_in: float = 0.0                       # seconds
    fade_out: float = 0.0                      # seconds


@dataclass
class Channel:
    name: str
    layers: list[Layer] = field(default_factory=list)   # layers[0] = base

    def synthesize(self) -> ActionList:
        """Return the synthesized ActionList for downstream consumption.

        Phase 2: returns a copy of the first enabled layer's actions.
        Phase 6: folds the full layer stack top-down with blend/span/fades.
        """
        for layer in self.layers:
            if layer.enabled:
                return layer.actions.copy()
        return ActionList()

    @classmethod
    def from_funscript(cls, fs: Funscript, name: str) -> Channel:
        """Build a Channel from a Funscript DTO — base layer = fs.actions."""
        base = Layer(actions=fs.actions.copy(), name="base")
        return cls(name=name, layers=[base])

    def to_funscript(
        self,
        metadata: FunscriptMetadata | None = None,
        version: str = "1.0",
        inverted: bool = False,
        range_: int = 100,
    ) -> Funscript:
        """Export this channel to a Funscript DTO via synthesize()."""
        return Funscript(
            actions=self.synthesize(),
            metadata=metadata or FunscriptMetadata(),
            version=version,
            inverted=inverted,
            range_=range_,
        )
