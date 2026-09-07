from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from bot.awareness.enemy.models import EnemyAwareness


class MacroPosture(Enum):
    """Coarse strategic pressure used to arbitrate economic spending.

    The posture is deliberately smaller than a complete strategy model.  It
    answers how risky spending is *right now*; the strategy profile still owns
    what the bot is trying to build.
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
