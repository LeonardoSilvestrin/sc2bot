from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

from .model import StrategicObjective


def _require_non_negative(weights: object) -> None:
    for item in fields(weights):  # type: ignore[arg-type]
        value = getattr(weights, item.name)
        if not (math.isfinite(value) and value >= 0.0):
            raise ValueError(f"{item.name} must be a finite, non-negative weight")


# Every weight is a magnitude. Whether a signal raises or lowers a score is
# fixed by the scoring function (see ``scoring.py``), so a weight never flips
# an objective's meaning when it is retuned.


@dataclass(frozen=True, slots=True)
class StabilizeWeights:
    """Immediate risk of our position deteriorating."""

    immediate_threat: float = 0.70
    base_exposure: float = 0.30
    military_deficit: float = 0.15

    def __post_init__(self) -> None:
        _require_non_negative(self)


@dataclass(frozen=True, slots=True)
class RecoverWeights:
    """Structurally behind, without an extreme crisis."""

    economic_deficit: float = 0.50
    military_deficit: float = 0.40
    territory_deficit: float = 0.15
    # 1 - home_security: a generally unstable position.
    instability: float = 0.15
    # A crisis is STABILIZE's, not RECOVER's.
    immediate_threat: float = 0.30

    def __post_init__(self) -> None:
        _require_non_negative(self)


@dataclass(frozen=True, slots=True)
class BuildAdvantageWeights:
    """Stable enough to keep growing before taking risks: the common state
    and the conservative fallback."""

    baseline: float = 0.40
    home_security: float = 0.25
    immediate_threat: float = 0.40
    military_deficit: float = 0.25
    economic_deficit: float = 0.25
    # Being clearly ahead already is a reason to stop only building.
    military_surplus: float = 0.30
    # Little knowledge keeps us here rather than taking risks.
    uncertainty: float = 0.15

    def __post_init__(self) -> None:
        _require_non_negative(self)


@dataclass(frozen=True, slots=True)
class TakeMapControlWeights:
    """Strong and stable enough to turn it into a better territorial
    position."""

    military_edge: float = 0.45
    # Map control needs a sufficient army, not an overwhelming one: the
    # military edge counts fully from this edge on ...
    military_sufficient: float = 0.5
    # ... and the confident edge beyond it hands over to PRESSURE.
    military_surplus: float = 0.60
    military_deficit: float = 0.30
    home_security: float = 0.15
    # Room left to take (1 - how far ahead on territory we already are),
    # only as far as the army supports taking it.
    territory_room: float = 0.25
    knowledge_confidence: float = 0.10
    immediate_threat: float = 0.40

    def __post_init__(self) -> None:
        _require_non_negative(self)
        if self.military_sufficient <= 0.0 or self.military_sufficient > 1.0:
            raise ValueError("military_sufficient must be within (0, 1]")


@dataclass(frozen=True, slots=True)
class PressureWeights:
    """A reliable enough edge to take the initiative against the enemy."""

    # Only the confident share of the edge is credited; the rest is reported
    # as a knowledge_confidence discount.
    military_edge: float = 0.80
    home_security: float = 0.20
    economic_edge: float = 0.10
    territory_edge: float = 0.10
    immediate_threat: float = 0.50
    # Flat penalty for incomplete knowledge, on top of the discounted edge.
    uncertainty: float = 0.20

    def __post_init__(self) -> None:
        _require_non_negative(self)


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Every tunable number behind the strategic direction, in one place.

    First, deliberately small guesses, left untuned until shadow-mode logs
    show where they are wrong. See ``docs/strategy.md``.
    """

    # Strategy is recomputed on this cadence and reused unchanged in between.
    update_interval_seconds: float = 1.0
    # A challenger must outscore the objective in force by this much ...
    switch_margin: float = 0.08
    # ... and the objective in force must have been held this long.
    minimum_dwell_seconds: float = 20.0
    # At or above this immediate threat, STABILIZE may replace the objective
    # in force before its dwell is over (the margin still applies). ``None``
    # disables the exception.
    emergency_threat: float | None = 0.8
    # Held from the first update until hysteresis allows a switch.
    initial_objective: StrategicObjective = StrategicObjective.BUILD_ADVANTAGE
    # A lead over the best other objective this large is full confidence.
    clear_lead: float = 0.25

    stabilize: StabilizeWeights = field(default_factory=StabilizeWeights)
    recover: RecoverWeights = field(default_factory=RecoverWeights)
    build_advantage: BuildAdvantageWeights = field(
        default_factory=BuildAdvantageWeights
    )
    take_map_control: TakeMapControlWeights = field(
        default_factory=TakeMapControlWeights
    )
    pressure: PressureWeights = field(default_factory=PressureWeights)

    def __post_init__(self) -> None:
        for name in ("update_interval_seconds", "minimum_dwell_seconds"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value >= 0.0):
                raise ValueError(f"{name} must be finite and not negative")
        if not 0.0 <= self.switch_margin <= 1.0:
            raise ValueError("switch_margin must be within [0, 1]")
        if self.emergency_threat is not None and not (
            0.0 <= self.emergency_threat <= 1.0
        ):
            raise ValueError("emergency_threat must be None or within [0, 1]")
        if not 0.0 < self.clear_lead <= 1.0:
            raise ValueError("clear_lead must be within (0, 1]")
