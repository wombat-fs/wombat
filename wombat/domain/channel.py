"""Channel — editable funscript unit owning a stack of Layers.

Phase 2: synthesize() was identity over the single enabled base layer.
Phase 6: folds the full stack with blend/span/fade envelopes via synthesis.py.

The seam: everything downstream (rendering, export, heatmap) consumes
synthesize(); editing always targets a specific Layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from wombat.domain.action import ActionList
from wombat.domain.funscript import Funscript, FunscriptMetadata

if TYPE_CHECKING:
    from wombat.domain.synthesis import SynthesisParams


class BlendMode(str, Enum):
    """Blend mode for a layer.  str mixin → value-based equality survives module reloads."""
    OVERRIDE = "override"
    ADDITIVE = "additive"


class FadeCurve(str, Enum):
    """Fade curve shape.  str mixin → value-based equality survives module reloads."""
    LINEAR = "linear"
    SMOOTH = "smooth"   # smoothstep


@dataclass
class Layer:
    actions: ActionList
    name: str = "base"
    enabled: bool = True
    # Envelope:
    blend: BlendMode = BlendMode.OVERRIDE
    span: tuple[float, float] | None = None   # None = whole timeline (w≡1)
    fade_in: float = 0.0                       # seconds
    fade_out: float = 0.0                      # seconds
    center: int = 50                           # additive reference (default 50)
    fade_curve: FadeCurve = FadeCurve.SMOOTH

    def weight_at(self, t: float, min_fade: float) -> float:
        """Weight envelope [0..1] at time t.

        span=None → always 1.0 (whole timeline, no boundary fades).
        Otherwise 0 outside span, ramps up/down over effective fade durations.
        min_fade is enforced at span edges so the signal stays continuous.
        """
        if not self.enabled:
            return 0.0
        if self.span is None:
            return 1.0
        start, end = self.span
        if t < start or t > end:
            return 0.0
        total = end - start
        eff_fi = max(min_fade, self.fade_in)
        eff_fo = max(min_fade, self.fade_out)
        if total > 0 and eff_fi + eff_fo > total:
            ratio = eff_fi / (eff_fi + eff_fo)
            eff_fi = total * ratio
            eff_fo = total - eff_fi
        if eff_fi > 0 and t < start + eff_fi:
            frac = (t - start) / eff_fi
            return self._apply_curve(frac)
        if eff_fo > 0 and t > end - eff_fo:
            frac = (end - t) / eff_fo
            return self._apply_curve(frac)
        return 1.0

    def value_at(self, t: float) -> float:
        """Linear-interpolated position at time t (clamped at endpoints)."""
        from wombat.domain.interpolate import value_at as _val
        return _val(self.actions, t)

    def _apply_curve(self, frac: float) -> float:
        frac = max(0.0, min(1.0, frac))
        if self.fade_curve == FadeCurve.SMOOTH:
            return frac * frac * (3.0 - 2.0 * frac)
        return frac


@dataclass
class Channel:
    name: str
    layers: list[Layer] = field(default_factory=list)   # layers[0] = base
    enabled: bool = True
    _synthesis_cache: dict = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def _invalidate_cache(self) -> None:
        self._synthesis_cache.clear()

    def synthesize(self, params: SynthesisParams | None = None) -> ActionList:
        """Return the synthesized ActionList for downstream consumption.

        Memoized per SynthesisParams: call _invalidate_cache() after any layer mutation.
        Identity: a single full-span, override, no-fade base layer → base actions exactly.
        With real layer stacks: delegates to domain/synthesis.py fold engine.
        """
        from wombat.domain.synthesis import (
            SynthesisParams as _SP,
            get_default_params as _get_default,
            synthesize as _synth,
        )
        if params is None:
            params = _get_default()
        cached = self._synthesis_cache.get(params)
        if cached is not None:
            return cached
        result = _synth(self.layers, params)
        self._synthesis_cache[params] = result
        return result

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
