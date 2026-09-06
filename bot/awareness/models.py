from __future__ import annotations

from dataclasses import dataclass

from bot.awareness.enemy.models import EnemyAwareness


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


@dataclass(frozen=True, slots=True)
class AwarenessSnapshot:
    """What the bot currently believes, derived from known facts."""

    enemy: EnemyAwareness
    relative_strength: RelativeStrength
    threat: ThreatAssessment
    updated_at: float
