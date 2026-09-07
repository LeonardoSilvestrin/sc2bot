from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from bot.world.knowledge.enemy.models import EnemyAwareness


class MacroPosture(Enum):
    """Coarse strategic pressure used to arbitrate economic spending.

    The posture describes how risky spending is right now; behavior policies
    still own what the bot is trying to build.
    """

    DEFENSE = auto()
    BALANCED = auto()
    GREED = auto()
    RECOVERY = auto()


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
