from __future__ import annotations

from dataclasses import dataclass, field

from .bases import BaseAwareness
from .belief import (
    ArmyBelief,
    ArmySupplyEstimate,
    BaseEstimate,
    EconomyBelief,
    EnemyArmyKnowledge,
    EnemyEconomyKnowledge,
    RelativeAssessment,
    RelativePosition,
    WorkerEstimate,
)
from .enemy import EnemyAwareness
from .posture import MacroPosture
from .spatial import SpatialField
from .territory import TerritorySnapshot


def _unknown_relative() -> RelativeAssessment:
    return RelativeAssessment(
        raw_state=RelativePosition.UNKNOWN,
        stable_state=RelativePosition.UNKNOWN,
        confidence=0.0,
    )


def _default_economy_belief() -> EconomyBelief:
    return EconomyBelief(
        own_workers=0,
        own_bases=0,
        enemy=EnemyEconomyKnowledge(
            workers=WorkerEstimate(observed=0, estimated=0, confidence=0.0),
            bases=BaseEstimate(confirmed=0, estimated=0, confidence=0.0),
        ),
        relative=_unknown_relative(),
    )


def _default_army_belief() -> ArmyBelief:
    return ArmyBelief(
        own_supply=0.0,
        enemy=EnemyArmyKnowledge(
            supply=ArmySupplyEstimate(observed=0.0, estimated=0.0, confidence=0.0),
            composition=(),
        ),
        relative=_unknown_relative(),
    )


@dataclass(frozen=True, slots=True)
class RelativeStrength:
    score: float
    confidence: float
    own_combat_units: int
    known_enemy_combat_units: int


@dataclass(frozen=True, slots=True)
class ThreatAssessment:
    visible_enemy_units: int
    known_anti_air_units: int
    visible_anti_air_units: int
    visible_enemy_combat_units: int = 0
    near_own_base_enemy_units: int = 0
    near_own_base_enemy_combat_units: int = 0


@dataclass(frozen=True, slots=True)
class AwarenessSnapshot:
    """What the bot currently believes, derived from known facts."""

    enemy: EnemyAwareness
    relative_strength: RelativeStrength
    threat: ThreatAssessment
    updated_at: float
    macro_posture: MacroPosture = MacroPosture.BALANCED
    bases: BaseAwareness = field(default_factory=BaseAwareness)
    economy: EconomyBelief = field(default_factory=_default_economy_belief)
    army: ArmyBelief = field(default_factory=_default_army_belief)
    spatial: SpatialField = field(default_factory=SpatialField)
    # Shadow mode: perceived territory, not yet read by any behavior or macro.
    territory: TerritorySnapshot = field(default_factory=TerritorySnapshot)
    # Populated only on the tick a stable economy/army belief actually
    # changes. ``FrameProcessor`` writes these diagnostics to the log;
    # Awareness itself performs no I/O.
    belief_changes: tuple[str, ...] = ()
